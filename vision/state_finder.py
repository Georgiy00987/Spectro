import os
import sys
import cv2
import numpy as np
sys.path.append(os.path.abspath('/'))
from core.utils import load_toml_as_dict

orig_screen_width, orig_screen_height = 1920, 1080

states_path = r"./images/states/"

star_drops_path = r"./images/star_drop_types/"
images_with_star_drop = []
for file in os.listdir(star_drops_path):
    if "star_drop" in file:
        images_with_star_drop.append(file)
images_with_star_drop.sort(key=lambda name: 0 if name in ("angelic_star_drop.png", "demonic_star_drop.png") else 1)
STAR_DROP_TEMPLATE_THRESHOLD = 0.97

end_results_path = r"./images/end_results/"

region_data = load_toml_as_dict("./cfg/lobby_config.toml")['template_matching']
super_debug = load_toml_as_dict("./cfg/general_config.toml")['super_debug'] == "yes"
_last_printed_state = None
if super_debug:
    debug_folder = "./debug_frames/"
    if not os.path.exists(debug_folder):
        os.makedirs(debug_folder)

def is_template_in_region(image, template_path, region, threshold=0.7):
    current_height, current_width = image.shape[:2]
    orig_x, orig_y, orig_width, orig_height = region
    width_ratio, height_ratio = current_width / orig_screen_width, current_height / orig_screen_height

    new_x, new_y = int(orig_x * width_ratio), int(orig_y * height_ratio)
    new_width, new_height = int(orig_width * width_ratio), int(orig_height * height_ratio)
    cropped_image = image[new_y:new_y + new_height, new_x:new_x + new_width]
    current_height, current_width = image.shape[:2]
    loaded_template = load_template(template_path, current_width, current_height)
    result = cv2.matchTemplate(cropped_image, loaded_template,
                               cv2.TM_CCOEFF_NORMED)
    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
    return max_val > threshold

cached_templates = {}

def load_template(image_path, width, height):
    if (image_path, width, height) in cached_templates:
        return cached_templates[(image_path, width, height)]
    current_width_ratio, current_height_ratio = width / orig_screen_width, height / orig_screen_height
    image = cv2.imread(image_path)
    orig_height, orig_width = image.shape[:2]
    resized_image = cv2.resize(image, (int(orig_width * current_width_ratio), int(orig_height * current_height_ratio)))
    cached_templates[(image_path, width, height)] = resized_image
    return resized_image

crop_region = load_toml_as_dict("./cfg/lobby_config.toml")['lobby']['trophy_observer']
_current_gamemode = load_toml_as_dict("./cfg/bot_config.toml").get("gamemode", "")

# Showdown has place-based results (1st-4th in trio) instead of victory/defeat.
# Each place may have multiple template variants (different backgrounds at
# different trophy ranges). Any matching variant counts as that place.
showdown_place_templates = {
    "1st": ["sd1st.png"],
    "2nd": ["sd2nd.png"],
    "4th": ["sd4th.png"],
    "3rd": ["sd3rd.png", "sd3rd_alt.png"],
}


SHOWDOWN_PLACE_THRESHOLD = 0.95


def refresh_runtime_config():
    global region_data, super_debug, crop_region, _current_gamemode
    lobby_config = load_toml_as_dict("./cfg/lobby_config.toml")
    general_config = load_toml_as_dict("./cfg/general_config.toml")
    bot_config = load_toml_as_dict("./cfg/bot_config.toml")
    region_data = lobby_config['template_matching']
    crop_region = lobby_config['lobby']['trophy_observer']
    super_debug = str(general_config.get("super_debug", "no")).lower() in ("yes", "true", "1")
    _current_gamemode = bot_config.get("gamemode", "")
    if super_debug and not os.path.exists("./debug_frames/"):
        os.makedirs("./debug_frames/")


def find_game_result(screenshot):
    if _current_gamemode == "showdown":
        for place, template_files in showdown_place_templates.items():
            for template_file in template_files:
                if is_template_in_region(
                    screenshot,
                    end_results_path + template_file,
                    crop_region,
                    threshold=SHOWDOWN_PLACE_THRESHOLD,
                ):
                    return place
        return False

    is_victory = is_template_in_region(screenshot, end_results_path + 'victory.png', crop_region)
    if is_victory:
        return "victory"

    is_defeat = is_template_in_region(screenshot, end_results_path + 'defeat.png', crop_region)
    if is_defeat:
        return "defeat"

    is_draw = is_template_in_region(screenshot, end_results_path + 'draw.png', crop_region)
    if is_draw:
        return "draw"
    return False



def get_in_game_state(image):
    game_result = is_in_end_of_a_match(image)
    if game_result: return f"end_{game_result}"
    if is_in_shop(image): return "shop"
    if is_in_offer_popup(image): return "popup"
    if is_in_team_invite_popup(image): return "popup"
    if is_in_match_making(image): return "match_making"
    if is_in_lobby(image): return "lobby"
    if is_in_event_info_popup(image): return "popup"
    if is_in_brawler_selection(image):
        return "brawler_selection"

    if is_in_brawl_pass(image) or is_in_star_road(image):
        return "shop"

    if is_in_star_drop(image):
        return "star_drop"

    if is_in_trophy_reward(image):
        return "trophy_reward"

    if is_in_prestige_reward(image):
        return "prestige_reward"

    if is_in_continue_popup(image):
        return "popup"

    if is_in_you_got_reward(image):
        return "you_got"

    return "match"


def is_in_shop(image) -> bool:
    return is_template_in_region(image, states_path + 'powerpoint.png', region_data["powerpoint"])


def is_in_brawler_selection(image) -> bool:
    return is_template_in_region(image, states_path + 'brawler_menu_task.png', region_data["brawler_menu_task"])


def is_in_you_got_reward(image) -> bool:
    """Detect the post-match "YOU GOT: ..." reward screen (e.g. NEW PLAYER ICON).

    Signature: a near-full-frame bright blue radial-burst background plus the
    bright yellow subtitle text (e.g. "NEW PLAYER ICON") below the reward card.
    The "YOU GOT:" title itself is white/outlined and unreliable, so we key on
    the dominant blue fill + yellow subtitle. Placed last in get_in_game_state
    so any definitive screen (lobby / brawler_selection / etc.) takes precedence.
    """
    h, w = image.shape[:2]
    if h == 0 or w == 0:
        return False
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)

    # 1) Dominant bright-blue radial-burst background across the whole frame.
    blue_mask = cv2.inRange(
        hsv,
        np.array((90, 60, 60), dtype=np.uint8),
        np.array((128, 255, 255), dtype=np.uint8),
    )
    blue_ratio = cv2.countNonZero(blue_mask) / max(1, h * w)

    # 2) Bright yellow subtitle text below the reward card ("NEW PLAYER ICON").
    ly0, ly1 = int(h * 0.55), int(h * 0.78)
    lx0, lx1 = int(w * 0.15), int(w * 0.85)
    lower = hsv[ly0:ly1, lx0:lx1]
    if lower.size == 0:
        return False
    yellow_mask = cv2.inRange(
        lower,
        np.array((16, 80, 120), dtype=np.uint8),
        np.array((38, 255, 255), dtype=np.uint8),
    )
    yellow_ratio = cv2.countNonZero(yellow_mask) / max(1, lower.shape[0] * lower.shape[1])

    if super_debug:
        print(f"[you_got] blue_ratio={blue_ratio:.3f} yellow_ratio={yellow_ratio:.4f}")

    return blue_ratio > 0.55 and yellow_ratio > 0.006


def is_in_offer_popup(image) -> bool:
    return is_template_in_region(image, states_path + 'close_popup.png', region_data["close_popup"])


def is_in_continue_popup(image) -> bool:
    """Попап «новый контент» (NEW RARE SKIN / новости): синяя CONTINUE слева
    и зелёная EQUIP NOW справа. Закрывается нажатием CONTINUE."""
    return get_continue_button_center(image) is not None


def get_continue_button_center(image, image_is_rgb=False):
    h, w = image.shape[:2]
    if h == 0 or w == 0:
        return None
    conv = cv2.COLOR_RGB2HSV if image_is_rgb else cv2.COLOR_BGR2HSV

    # Guard against false positives during match gameplay. The real new-content
    # popup has a large blue/purple modal/background in the middle of the screen,
    # while gameplay can have green/white controls in the lower action area that
    # look like CONTINUE/EQUIP buttons.
    modal = image[int(h * 0.10):int(h * 0.72), int(w * 0.12):int(w * 0.88)]
    if modal.size == 0:
        return None
    modal_hsv = cv2.cvtColor(modal, conv)
    blue = cv2.inRange(modal_hsv, np.array((88, 45, 45), np.uint8), np.array((130, 255, 255), np.uint8))
    purple = cv2.inRange(modal_hsv, np.array((130, 35, 45), np.uint8), np.array((165, 255, 255), np.uint8))
    bright = cv2.inRange(modal_hsv, np.array((0, 0, 130), np.uint8), np.array((179, 95, 255), np.uint8))
    modal_area = max(1, modal.shape[0] * modal.shape[1])
    modal_color_ratio = (cv2.countNonZero(blue) + cv2.countNonZero(purple)) / modal_area
    modal_text_ratio = cv2.countNonZero(bright) / modal_area
    if modal_color_ratio < 0.16 or modal_text_ratio < 0.004:
        return None

    ry0 = int(h * 0.72)
    crop = image[ry0:h, 0:w]
    if crop.size == 0:
        return None
    hsv = cv2.cvtColor(crop, conv)
    ch, cw = crop.shape[:2]
    min_area = max(250, ch * cw * 0.008)
    white = cv2.inRange(hsv, np.array((0, 0, 170), np.uint8), np.array((179, 95, 255), np.uint8))
    # Anchor: green EQUIP NOW button on the right, solid, with white text.
    green = cv2.inRange(hsv, np.array((40, 90, 80), np.uint8), np.array((85, 255, 255), np.uint8))
    green = cv2.morphologyEx(green, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    gcnts, _ = cv2.findContours(green, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    equip = None
    for c in gcnts:
        a = cv2.contourArea(c)
        bx, by, bw, bh = cv2.boundingRect(c)
        if a < min_area or bw < cw * 0.10 or bh < ch * 0.10:
            continue
        if a / max(1, bw * bh) < 0.55:
            continue
        if bx + bw / 2 <= cw * 0.58:
            continue
        if by + bh / 2 < ch * 0.22 or by + bh / 2 > ch * 0.86:
            continue
        if cv2.countNonZero(white[by:by + bh, bx:bx + bw]) / max(1, bw * bh) < 0.04:
            continue
        if equip is None or a > equip[0]:
            equip = (a, bx, by, bw, bh)
    if equip is None:
        return None
    _, ebx, eby, ebw, ebh = equip
    e_cx, e_cy = ebx + ebw / 2, eby + ebh / 2
    # CONTINUE: white text label on the same row, to the left of EQUIP.
    wmask = cv2.morphologyEx(white, cv2.MORPH_CLOSE, np.ones((3, 17), np.uint8))
    wcnts, _ = cv2.findContours(wmask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best = None
    for c in wcnts:
        if cv2.contourArea(c) < 80:
            continue
        bx, by, bw, bh = cv2.boundingRect(c)
        tcx, tcy = bx + bw / 2, by + bh / 2
        if tcx >= e_cx:
            continue
        if abs(tcy - e_cy) > ch * 0.14:
            continue
        if tcx < cw * 0.30:
            continue
        if best is None or tcx > best[0]:
            best = (tcx, bx, by, bw, bh)
    if best is None:
        return None
    _, bx, by, bw, bh = best
    return int(bx + bw / 2), int(ry0 + by + bh / 2)


def get_event_info_close_button_center(image, image_is_rgb=False):
    """Return the (x, y) center of the red X close button on the EVENT INFO
    (event details) popup, or None.

    The button is a small, solid red rounded square holding a white X, sitting
    at the top-right corner of the centered event panel. We scan the upper band
    for a roughly square, solid red blob that contains a white mark.
    """
    h, w = image.shape[:2]
    if h == 0 or w == 0:
        return None

    ry0, ry1 = int(h * 0.05), int(h * 0.45)
    rx0, rx1 = int(w * 0.45), int(w * 0.97)
    crop = image[ry0:ry1, rx0:rx1]
    if crop.size == 0:
        return None

    conv = cv2.COLOR_RGB2HSV if image_is_rgb else cv2.COLOR_BGR2HSV
    hsv = cv2.cvtColor(crop, conv)

    red_low = cv2.inRange(hsv, np.array((0, 120, 110), np.uint8), np.array((10, 255, 255), np.uint8))
    red_high = cv2.inRange(hsv, np.array((170, 120, 110), np.uint8), np.array((179, 255, 255), np.uint8))
    red = cv2.bitwise_or(red_low, red_high)
    red = cv2.morphologyEx(red, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    white = cv2.inRange(hsv, np.array((0, 0, 170), np.uint8), np.array((179, 90, 255), np.uint8))

    cnts, _ = cv2.findContours(red, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best = None
    for c in cnts:
        area = cv2.contourArea(c)
        bx, by, bw, bh = cv2.boundingRect(c)
        if bw == 0 or bh == 0:
            continue
        if bw < w * 0.02 or bw > w * 0.10:
            continue
        if bh < h * 0.03 or bh > h * 0.12:
            continue
        aspect = bw / float(bh)
        if aspect < 0.6 or aspect > 1.9:
            continue
        if area / float(bw * bh) < 0.65:                 # solid filled square
            continue
        white_ratio = cv2.countNonZero(white[by:by + bh, bx:bx + bw]) / float(bw * bh)
        if white_ratio < 0.05 or white_ratio > 0.45:     # must hold a white X
            continue
        score = bx - by                                  # prefer top-right corner
        if best is None or score > best[0]:
            best = (score, bx, by, bw, bh)
    if best is None:
        return None
    _, bx, by, bw, bh = best
    return int(rx0 + bx + bw / 2), int(ry0 + by + bh / 2)



def is_in_event_info_popup(image) -> bool:
    """Detect the small EVENT INFO / map-preview popup without catching normal lobby UI."""
    # Normal lobby has several HUD anchors and can contain red notification badges
    # in the same broad top-right area. If lobby HUD is visible, do not treat a red
    # blob as an event-info close button. Real event info overlays hide these anchors.
    if is_lobby_hud_visible(image, required_anchors=2):
        return False

    center = (
        get_event_info_close_button_center(image, image_is_rgb=False)
        or get_event_info_close_button_center(image, image_is_rgb=True)
    )
    if center is None:
        return False

    h, w = image.shape[:2]
    x, y = center
    # Event-info close is around the top-right of the centered event panel, not
    # in the extreme screen corner or lower lobby cards.
    if not (w * 0.56 <= x <= w * 0.88 and h * 0.07 <= y <= h * 0.30):
        return False

    # Require a large central panel/map area. This removes false positives from
    # isolated lobby badges while keeping the actual map-preview screenshot.
    panel = crop_scaled_region(image, [250, 100, 1420, 780])
    if panel.size == 0:
        return False
    blue_ratio = mask_ratio(panel, (85, 45, 45), (130, 255, 255))
    dark_ratio = mask_ratio(panel, (0, 0, 0), (179, 255, 85))
    white_ratio = mask_ratio(panel, (0, 0, 155), (179, 95, 255))
    return (blue_ratio > 0.18 or dark_ratio > 0.12) and white_ratio > 0.006

def get_matchmaking_exit_button_center(image):
    region = region_data.get("exit_match_making", [1600, 925, 295, 135])
    template_path = states_path + "exit_match_making.png"
    if os.path.exists(template_path) and not is_template_in_region(
            image,
            template_path,
            region,
            threshold=0.82,
    ):
        return None

    current_height, current_width = image.shape[:2]
    width_ratio = current_width / orig_screen_width
    height_ratio = current_height / orig_screen_height

    # Matchmaking has a large red Exit button fixed in the lower-right corner.
    # Require the exact Exit template first, then use the color/shape pass only
    # to return a scaled click center. In-match red UI can otherwise resemble a
    # cancel button closely enough to cause false match_making states.
    x = int(region[0] * width_ratio)
    y = int(region[1] * height_ratio)
    w = int(region[2] * width_ratio)
    h = int(region[3] * height_ratio)
    crop = image[y:y + h, x:x + w]
    if crop.size == 0:
        return None

    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    red_low = cv2.inRange(
        hsv,
        np.array((0, 90, 90), dtype=np.uint8),
        np.array((10, 255, 255), dtype=np.uint8),
    )
    red_high = cv2.inRange(
        hsv,
        np.array((170, 90, 90), dtype=np.uint8),
        np.array((179, 255, 255), dtype=np.uint8),
    )
    red_mask = cv2.bitwise_or(red_low, red_high)
    red_mask = cv2.morphologyEx(red_mask, cv2.MORPH_CLOSE, np.ones((7, 7), dtype=np.uint8))
    contours, _ = cv2.findContours(red_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    min_area = max(600, crop.shape[0] * crop.shape[1] * 0.18)
    candidates = []
    for contour in contours:
        area = cv2.contourArea(contour)
        bx, by, bw, bh = cv2.boundingRect(contour)
        if area < min_area or bw < w * 0.45 or bh < h * 0.30:
            continue
        button_part = crop[by:by + bh, bx:bx + bw]
        if button_part.size == 0:
            continue
        white_ratio = mask_ratio(button_part, (0, 0, 165), (179, 95, 255))
        dark_ratio = mask_ratio(button_part, (0, 0, 0), (179, 255, 75))
        if white_ratio < 0.015 or dark_ratio < 0.025:
            continue
        candidates.append((area, bx, by, bw, bh))

    if not candidates:
        return None
    _, bx, by, bw, bh = max(candidates, key=lambda item: item[0])
    return int(x + bx + bw / 2), int(y + by + bh / 2)


def is_matchmaking_tip_visible(image):
    top = crop_scaled_region(image, [650, 95, 620, 140])
    if top.size == 0:
        return False
    white_ratio = mask_ratio(top, (0, 0, 170), (179, 90, 255))
    dark_ratio = mask_ratio(top, (0, 0, 0), (179, 255, 80))
    return white_ratio > 0.035 and dark_ratio > 0.025


def is_matchmaking_background_visible(image):
    center = crop_scaled_region(image, [0, 0, 1920, 840])
    if center.size == 0:
        return False
    red_ratio = mask_ratio(center, (0, 60, 65), (12, 255, 255)) + mask_ratio(center, (170, 60, 65), (179, 255, 255))
    dark_ratio = mask_ratio(center, (0, 0, 0), (179, 255, 90))
    return red_ratio > 0.12 and dark_ratio > 0.035


def is_in_match_making(image) -> bool:
    return (
        get_matchmaking_exit_button_center(image) is not None
        and is_matchmaking_tip_visible(image)
        and is_matchmaking_background_visible(image)
    )


def get_team_invite_reject_button_center(image, image_is_rgb=False):
    current_height, current_width = image.shape[:2]
    width_ratio = current_width / orig_screen_width
    height_ratio = current_height / orig_screen_height

    region = [480, 185, 960, 700]
    x = int(region[0] * width_ratio)
    y = int(region[1] * height_ratio)
    w = int(region[2] * width_ratio)
    h = int(region[3] * height_ratio)
    crop = image[y:y + h, x:x + w]
    if crop.size == 0:
        return None

    color_conversion = cv2.COLOR_RGB2HSV if image_is_rgb else cv2.COLOR_BGR2HSV
    hsv = cv2.cvtColor(crop, color_conversion)
    blue_mask = cv2.inRange(
        hsv,
        np.array((90, 80, 80), dtype=np.uint8),
        np.array((120, 255, 255), dtype=np.uint8),
    )
    blue_ratio = cv2.countNonZero(blue_mask) / max(1, crop.shape[0] * crop.shape[1])
    if blue_ratio < 0.30:
        return None

    y_off = int(h * 0.45)
    lower_half = hsv[y_off:h, :]
    min_area = max(600, crop.shape[0] * crop.shape[1] * 0.015)

    def _qualifying_blobs(mask):
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        out = []
        for contour in contours:
            area = cv2.contourArea(contour)
            bx, by, bw, bh = cv2.boundingRect(contour)
            if area < min_area or bw < w * 0.18 or bh < h * 0.08:
                continue
            # Solidity (filled fraction of bbox). Real buttons are solid rounded
            # rects (>=0.6); sprawling lobby grass / decorations are sparser.
            if area / max(1, bw * bh) < 0.60:
                continue
            out.append((area, bx, by, bw, bh))
        return out

    red_mask_low = cv2.inRange(lower_half, np.array((0, 90, 90), dtype=np.uint8), np.array((10, 255, 255), dtype=np.uint8))
    red_mask_high = cv2.inRange(lower_half, np.array((170, 90, 90), dtype=np.uint8), np.array((179, 255, 255), dtype=np.uint8))
    green_mask = cv2.inRange(lower_half, np.array((40, 90, 90), dtype=np.uint8), np.array((85, 255, 255), dtype=np.uint8))

    # Reject button is on the LEFT half of the popup.
    reds = [b for b in _qualifying_blobs(cv2.bitwise_or(red_mask_low, red_mask_high)) if b[1] <= w * 0.55]
    greens = _qualifying_blobs(green_mask)
    if not reds or not greens:
        return None

    # A genuine team-invite popup shows the red "reject" and green "accept"
    # buttons as a MATCHED PAIR: same size, same row, green directly right of
    # red. The lobby merely has an unrelated red UI element on the left and a
    # large green grass patch on the right (different size, misaligned, sparse).
    reds.sort(key=lambda item: -item[0])
    for (_, rbx, rby, rbw, rbh) in reds:
        r_cx = rbx + rbw / 2
        r_cy = rby + rbh / 2
        for (_, gbx, gby, gbw, gbh) in greens:
            g_cx = gbx + gbw / 2
            g_cy = gby + gbh / 2
            if not (g_cx > w * 0.5 and g_cx > r_cx):
                continue
            if min(rbh, gbh) / max(rbh, gbh) < 0.72:   # similar height (paired)
                continue
            if min(rbw, gbw) / max(rbw, gbw) < 0.55:   # similar width
                continue
            if abs(r_cy - g_cy) > h * 0.07:             # aligned on the same row
                continue
            return int(x + rbx + rbw / 2), int(y + y_off + rby + rbh / 2)

    return None


def is_in_team_invite_popup(image) -> bool:
    if is_in_brawler_selection(image) or is_in_shop(image):
        return False
    return get_team_invite_reject_button_center(image) is not None and is_lobby_hud_visible(image, required_anchors=2)


def is_in_lobby(image) -> bool:
    return is_lobby_hud_visible(image)


def crop_scaled_region(image, region):
    current_height, current_width = image.shape[:2]
    orig_x, orig_y, orig_width, orig_height = region
    width_ratio, height_ratio = current_width / orig_screen_width, current_height / orig_screen_height
    x = int(orig_x * width_ratio)
    y = int(orig_y * height_ratio)
    width = int(orig_width * width_ratio)
    height = int(orig_height * height_ratio)
    return image[y:y + height, x:x + width]


def mask_ratio(crop, lower, upper):
    if crop.size == 0:
        return 0.0
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array(lower, dtype=np.uint8), np.array(upper, dtype=np.uint8))
    return cv2.countNonZero(mask) / max(1, crop.shape[0] * crop.shape[1])


def get_starr_nova_got_it_button_center(image):
    current_height, current_width = image.shape[:2]
    width_ratio = current_width / orig_screen_width
    height_ratio = current_height / orig_screen_height

    # Fixed event-info layout: large green "GOT IT!" button centered near the
    # bottom. Region is intentionally tight so lobby/match green UI cannot
    # trigger it.
    button_crop = crop_scaled_region(image, [690, 835, 560, 190])
    if button_crop.size == 0:
        return None

    hsv = cv2.cvtColor(button_crop, cv2.COLOR_BGR2HSV)
    green_mask = cv2.inRange(
        hsv,
        np.array((48, 120, 120), dtype=np.uint8),
        np.array((76, 255, 255), dtype=np.uint8),
    )
    green_mask = cv2.morphologyEx(green_mask, cv2.MORPH_CLOSE, np.ones((7, 7), dtype=np.uint8))
    contours, _ = cv2.findContours(green_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    x0 = int(690 * width_ratio)
    y0 = int(835 * height_ratio)
    min_area = max(800, button_crop.shape[0] * button_crop.shape[1] * 0.16)
    candidates = []
    for contour in contours:
        area = cv2.contourArea(contour)
        bx, by, bw, bh = cv2.boundingRect(contour)
        if area < min_area or bw < button_crop.shape[1] * 0.35 or bh < button_crop.shape[0] * 0.28:
            continue
        button_part = button_crop[by:by + bh, bx:bx + bw]
        if button_part.size == 0:
            continue
        white_ratio = mask_ratio(button_part, (0, 0, 150), (179, 120, 255))
        dark_ratio = mask_ratio(button_part, (0, 0, 0), (179, 255, 80))
        if white_ratio < 0.015 or dark_ratio < 0.03:
            continue
        candidates.append((area, bx, by, bw, bh))

    if not candidates:
        return None
    _, bx, by, bw, bh = max(candidates, key=lambda item: item[0])
    return int(x0 + bx + bw / 2), int(y0 + by + bh / 2)


def is_starr_nova_info_screen(image):
    button_center = get_starr_nova_got_it_button_center(image)
    if button_center is None:
        return False
    starr_nova_region = region_data.get("starr_nova_event")
    if starr_nova_region and os.path.exists(states_path + "starr_nova_event.png"):
        if is_template_in_region(
                image,
                states_path + "starr_nova_event.png",
                starr_nova_region,
                threshold=0.78,
        ):
            return True

    # The screen is mostly grayscale manga panels, with cyan headings and the
    # bright event logo. These anchors make the green button check specific to
    # this event screen instead of any random confirmation button.
    full_hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    low_sat_ratio = cv2.countNonZero(
        cv2.inRange(full_hsv[:, :, 1], np.array(0, dtype=np.uint8), np.array(55, dtype=np.uint8))
    ) / max(1, image.shape[0] * image.shape[1])
    if low_sat_ratio < 0.45:
        return False

    top_region = crop_scaled_region(image, [500, 35, 920, 190])
    mid_region = crop_scaled_region(image, [0, 430, 1920, 300])
    if top_region.size == 0 or mid_region.size == 0:
        return False
    top_white = mask_ratio(top_region, (0, 0, 170), (179, 90, 255))
    top_cyan = mask_ratio(top_region, (82, 80, 120), (100, 255, 255))
    mid_cyan = mask_ratio(mid_region, (82, 90, 110), (100, 255, 255))
    return top_white > 0.025 and top_cyan > 0.006 and mid_cyan > 0.012


def is_lobby_hud_visible(image, required_anchors=3) -> bool:
    anchors = [
        is_lobby_play_button_visible(image),
        is_lobby_currency_bar_visible(image),
        is_lobby_quests_button_visible(image),
        is_lobby_menu_button_visible(image),
    ]
    return sum(1 for value in anchors if value) >= required_anchors


def is_lobby_play_button_visible(image) -> bool:
    current_height, current_width = image.shape[:2]
    width_ratio = current_width / orig_screen_width
    height_ratio = current_height / orig_screen_height

    region = [1260, 820, 610, 225]
    x = int(region[0] * width_ratio)
    y = int(region[1] * height_ratio)
    w = int(region[2] * width_ratio)
    h = int(region[3] * height_ratio)
    crop = image[y:y + h, x:x + w]
    if crop.size == 0:
        return False

    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    yellow_mask = cv2.inRange(
        hsv,
        np.array((15, 90, 120), dtype=np.uint8),
        np.array((42, 255, 255), dtype=np.uint8),
    )
    yellow_pixels = cv2.countNonZero(yellow_mask)
    yellow_ratio = yellow_pixels / max(1, crop.shape[0] * crop.shape[1])
    if yellow_ratio < 0.28:
        return False

    contours, _ = cv2.findContours(yellow_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return False
    largest = max(contours, key=cv2.contourArea)
    bx, by, bw, bh = cv2.boundingRect(largest)
    return bw > w * 0.45 and bh > h * 0.35


def is_lobby_currency_bar_visible(image) -> bool:
    crop = crop_scaled_region(image, [1120, 0, 620, 95])
    if crop.size == 0:
        return False
    yellow_ratio = mask_ratio(crop, (16, 80, 120), (42, 255, 255))
    green_ratio = mask_ratio(crop, (45, 80, 110), (88, 255, 255))
    white_ratio = mask_ratio(crop, (0, 0, 170), (179, 95, 255))
    dark_ratio = mask_ratio(crop, (0, 0, 0), (179, 255, 80))
    return yellow_ratio > 0.018 and green_ratio > 0.010 and white_ratio > 0.035 and dark_ratio > 0.15


def is_lobby_quests_button_visible(image) -> bool:
    crop = crop_scaled_region(image, [240, 850, 340, 220])
    if crop.size == 0:
        return False
    cyan_ratio = mask_ratio(crop, (82, 50, 110), (112, 255, 255))
    white_ratio = mask_ratio(crop, (0, 0, 160), (179, 90, 255))
    orange_ratio = mask_ratio(crop, (8, 80, 100), (32, 255, 255))
    dark_ratio = mask_ratio(crop, (0, 0, 0), (179, 255, 90))
    return cyan_ratio > 0.025 and white_ratio > 0.055 and orange_ratio > 0.015 and dark_ratio > 0.20


def is_lobby_menu_button_visible(image) -> bool:
    if is_template_in_region(image, states_path + 'lobby_menu.png', region_data["lobby_menu"]):
        return True
    crop = crop_scaled_region(image, [1760, 0, 160, 100])
    if crop.size == 0:
        return False
    white_ratio = mask_ratio(crop, (0, 0, 175), (179, 80, 255))
    dark_ratio = mask_ratio(crop, (0, 0, 0), (179, 255, 90))
    return white_ratio > 0.05 and dark_ratio > 0.18


def is_in_end_of_a_match(image):
    return find_game_result(image)



def is_in_trophy_reward(image):
    return is_template_in_region(image, states_path + 'trophies_screen.png', region_data["trophies_screen"])


def count_hsv_in_region(image, region, lower, upper):
    current_height, current_width = image.shape[:2]
    orig_x, orig_y, orig_width, orig_height = region
    width_ratio, height_ratio = current_width / orig_screen_width, current_height / orig_screen_height
    x = int(orig_x * width_ratio)
    y = int(orig_y * height_ratio)
    width = int(orig_width * width_ratio)
    height = int(orig_height * height_ratio)
    crop = image[y:y + height, x:x + width]
    if crop.size == 0:
        return 0
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array(lower, dtype=np.uint8), np.array(upper, dtype=np.uint8))
    return int(cv2.countNonZero(mask))


def get_prestige_next_button_center(image):
    current_height, current_width = image.shape[:2]
    width_ratio = current_width / orig_screen_width
    height_ratio = current_height / orig_screen_height

    button_region = [1040, 760, 620, 250]
    x = int(button_region[0] * width_ratio)
    y = int(button_region[1] * height_ratio)
    w = int(button_region[2] * width_ratio)
    h = int(button_region[3] * height_ratio)
    button_crop = image[y:y + h, x:x + w]
    if button_crop.size == 0:
        return None

    hsv = cv2.cvtColor(button_crop, cv2.COLOR_BGR2HSV)
    green_mask = cv2.inRange(
        hsv,
        np.array((45, 120, 110), dtype=np.uint8),
        np.array((72, 255, 255), dtype=np.uint8),
    )
    contours, _ = cv2.findContours(green_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    min_area = max(400, button_crop.shape[0] * button_crop.shape[1] * 0.04)
    candidates = []
    for contour in contours:
        area = cv2.contourArea(contour)
        bx, by, bw, bh = cv2.boundingRect(contour)
        if area < min_area or bw < w * 0.20 or bh < h * 0.15:
            continue
        button_part = button_crop[by:by + bh, bx:bx + bw]
        if button_part.size == 0:
            continue
        text_hsv = cv2.cvtColor(button_part, cv2.COLOR_BGR2HSV)
        white_mask = cv2.inRange(
            text_hsv,
            np.array((0, 0, 160), dtype=np.uint8),
            np.array((179, 100, 255), dtype=np.uint8),
        )
        white_pixels = cv2.countNonZero(white_mask)
        if white_pixels < max(80, int(button_part.shape[0] * button_part.shape[1] * 0.02)):
            continue
        candidates.append((area, bx, by, bw, bh))

    if not candidates:
        return None

    _, bx, by, bw, bh = max(candidates, key=lambda item: item[0])
    return int(x + bx + bw / 2), int(y + by + bh / 2)


def has_prestige_badge_shape(image):
    current_height, current_width = image.shape[:2]
    width_ratio = current_width / orig_screen_width
    height_ratio = current_height / orig_screen_height
    badge_region = [1060, 120, 680, 560]
    x = int(badge_region[0] * width_ratio)
    y = int(badge_region[1] * height_ratio)
    w = int(badge_region[2] * width_ratio)
    h = int(badge_region[3] * height_ratio)
    crop = image[y:y + h, x:x + w]
    if crop.size == 0:
        return False

    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    blue_mask = cv2.inRange(
        hsv,
        np.array((96, 90, 90), dtype=np.uint8),
        np.array((126, 255, 255), dtype=np.uint8),
    )
    blue_mask = cv2.morphologyEx(
        blue_mask,
        cv2.MORPH_CLOSE,
        np.ones((9, 9), dtype=np.uint8),
    )
    contours, _ = cv2.findContours(blue_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return False

    scale = max(0.05, width_ratio * height_ratio)
    min_area = int(22000 * scale)
    min_width = int(180 * width_ratio)
    min_height = int(160 * height_ratio)
    for contour in contours:
        area = cv2.contourArea(contour)
        bx, by, bw, bh = cv2.boundingRect(contour)
        if area >= min_area and bw >= min_width and bh >= min_height:
            return True
    return False


def is_in_prestige_reward(image):
    button_center = get_prestige_next_button_center(image)
    if button_center is None:
        return False
    if not has_prestige_badge_shape(image):
        return False

    prestige_purple = count_hsv_in_region(
        image,
        [980, 80, 760, 660],
        (124, 80, 90),
        (162, 255, 255),
    )
    prestige_blue = count_hsv_in_region(
        image,
        [1060, 120, 650, 540],
        (95, 80, 80),
        (125, 255, 255),
    )
    scale = max(0.05, (image.shape[1] / orig_screen_width) * (image.shape[0] / orig_screen_height))
    return prestige_purple > int(18000 * scale) and prestige_blue > int(12000 * scale)



def is_in_brawl_pass(image):
    return is_template_in_region(image, states_path + 'brawl_pass_house.PNG', region_data['brawl_pass_house'])


def is_in_star_road(image):
    return is_template_in_region(image, states_path + "go_back_arrow.png", region_data['go_back_arrow'])


def is_in_star_drop(image):
    return get_star_drop_type(image) is not None


def get_star_drop_type(image):
    for image_filename in images_with_star_drop:
        if is_template_in_region(
                image,
                star_drops_path + image_filename,
                region_data['star_drop'],
                threshold=STAR_DROP_TEMPLATE_THRESHOLD,
        ):
            if image_filename == "angelic_star_drop.png":
                return "angelic"
            if image_filename == "demonic_star_drop.png":
                return "demonic"
            if not has_standard_star_drop_screen_context(image):
                return None
            return "standard"
    return None


def has_standard_star_drop_screen_context(image):
    background = crop_scaled_region(image, [340, 75, 1240, 830])
    if background.size == 0:
        return False

    hsv = cv2.cvtColor(background, cv2.COLOR_BGR2HSV)
    green_mask = cv2.inRange(
        hsv,
        np.array((38, 55, 55), dtype=np.uint8),
        np.array((92, 255, 255), dtype=np.uint8),
    )
    green_ratio = cv2.countNonZero(green_mask) / max(1, background.shape[0] * background.shape[1])
    if green_ratio < 0.16:
        return False

    top_title = crop_scaled_region(image, [690, 20, 540, 155])
    if top_title.size == 0:
        return False
    title_hsv = cv2.cvtColor(top_title, cv2.COLOR_BGR2HSV)
    bright_text = cv2.inRange(
        title_hsv,
        np.array((35, 0, 120), dtype=np.uint8),
        np.array((95, 255, 255), dtype=np.uint8),
    )
    return cv2.countNonZero(bright_text) > int(2200 * (image.shape[1] / orig_screen_width) * (image.shape[0] / orig_screen_height))


def is_in_daily_wins_drop(image):
    current_height, current_width = image.shape[:2]
    width_ratio, height_ratio = current_width / orig_screen_width, current_height / orig_screen_height

    def scaled_region(region):
        x, y, w, h = region
        return (
            int(x * width_ratio),
            int(y * height_ratio),
            int(w * width_ratio),
            int(h * height_ratio),
        )

    cx, cy, cw, ch = scaled_region([430, 90, 900, 760])
    center = image[cy:cy + ch, cx:cx + cw]
    if center.size == 0:
        return False

    hsv = cv2.cvtColor(center, cv2.COLOR_BGR2HSV)
    bright_green_mask = cv2.inRange(
        hsv,
        np.array((42, 100, 120), dtype=np.uint8),
        np.array((78, 255, 255), dtype=np.uint8),
    )
    bright_green_pixels = cv2.countNonZero(bright_green_mask)
    green_ratio = bright_green_pixels / max(1, center.shape[0] * center.shape[1])
    if green_ratio < 0.10:
        return False

    tx, ty, tw, th = scaled_region([0, 0, 520, 170])
    title = image[ty:ty + th, tx:tx + tw]
    if title.size == 0:
        return False

    title_hsv = cv2.cvtColor(title, cv2.COLOR_BGR2HSV)
    white_mask = cv2.inRange(
        title_hsv,
        np.array((0, 0, 160), dtype=np.uint8),
        np.array((179, 80, 255), dtype=np.uint8),
    )
    white_pixels = cv2.countNonZero(white_mask)
    return white_pixels > int(1800 * width_ratio * height_ratio)

def get_state(screenshot):
    global _last_printed_state
    refresh_runtime_config()
    screenshot_bgr = cv2.cvtColor(screenshot, cv2.COLOR_RGB2BGR)
    if super_debug: cv2.imwrite(f"./debug_frames/state_screenshot_{len(os.listdir('./debug_frames'))}.png", screenshot_bgr)
    state = get_in_game_state(screenshot_bgr)
    if super_debug or state != _last_printed_state:
        print(f"State: {state}")
        _last_printed_state = state
    return state
