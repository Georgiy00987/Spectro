import os.path
import sys

import asyncio
import time

import cv2
import numpy as np

from vision.state_finder import (
    get_state,
    find_game_result,
    is_in_prestige_reward,
    get_prestige_next_button_center,
    get_team_invite_reject_button_center,
    get_continue_button_center,
    get_event_info_close_button_center,
    get_star_drop_type,
)
from game.trophy_observer import TrophyObserver
from core.utils import find_template_center, load_toml_as_dict, async_notify_user, \
    save_brawler_data, extract_text_strings, load_brawl_stars_api_config, fetch_brawl_stars_player, fetch_brawl_stars_player_by_tag, normalize_brawler_name, config_bool
from game.adaptive_brain import AdaptiveBrain

debug = load_toml_as_dict("cfg/general_config.toml")['super_debug'] == "yes"


def load_image(image_path, scale_factor):
    # Load the image
    image = cv2.imread(image_path)
    orig_height, orig_width = image.shape[:2]

    # Calculate the new dimensions based on the scale factor
    new_width = int(orig_width * scale_factor)
    new_height = int(orig_height * scale_factor)

    # Resize the image
    resized_image = cv2.resize(image, (new_width, new_height))
    return resized_image

class StageManager:

    def __init__(self, brawlers_data, lobby_automator, window_controller):
        self.Lobby_automation = lobby_automator
        self.lobby_config = load_toml_as_dict("./cfg/lobby_config.toml")
        self.close_popup_icon = None
        self.brawlers_pick_data = brawlers_data
        self.started_trophies_by_brawler = {}
        for brawler in brawlers_data:
            name = str(brawler.get("brawler", "")).lower()
            if name:
                self.started_trophies_by_brawler[name] = brawler.get("trophies", 0)
        brawler_list = [brawler["brawler"] for brawler in brawlers_data]
        self.Trophy_observer = TrophyObserver(brawler_list)
        bot_config = load_toml_as_dict("cfg/bot_config.toml")
        adaptive_enabled = config_bool(bot_config.get("adaptive_brain_enabled"), True)
        adaptive_window = int(bot_config.get("adaptive_brain_window", 20))
        self.adaptive_brain = AdaptiveBrain(enabled=adaptive_enabled, window_size=adaptive_window)
        print(self.adaptive_brain.summary())
        self.time_since_last_stat_change = time.time()
        # Guards against recording trophies twice when end_game() is re-entered
        # on the same end-of-match screen (e.g. because the dismiss button
        # didn't clear the screen before the outer loop called us again).
        self.last_recorded_result_time = 0.0
        self.last_recorded_result = None
        self.active_end_result = None
        self.last_team_invite_reject_time = 0.0
        self.last_shop_exit_time = 0.0
        self.stop_after_post_match_rewards = False
        self.completion_notification_sent = False
        self.api_selection_checks_remaining = 3
        self.force_reselect_current_brawler = False
        time_thresholds = load_toml_as_dict("./cfg/time_tresholds.toml")
        self.end_screen_dismiss_delay = float(time_thresholds.get("end_screen_dismiss_delay", 0.35))
        self.window_controller = window_controller
        self.states = {
            'shop': self.quit_shop,
            'brawler_selection': self.quit_shop,
            'popup': self.close_pop_up,
            'match': lambda: 0,
            'match_making': lambda: self.window_controller.keys_up(list("wasd")),
            'end_draw': self.end_game,
            'end_victory': self.end_game,
            'end_defeat': self.end_game,
            # Showdown trio: finishing places 1-4
            'end_1st': self.end_game,
            'end_2nd': self.end_game,
            'end_3rd': self.end_game,
            'end_4th': self.end_game,
            'lobby': self.start_game,
            'star_drop': self.handle_star_drop,
            'prestige_reward': self.handle_prestige_reward,
            'trophy_reward': lambda: self.window_controller.press_key("Q"),
            'you_got': self.handle_you_got,
        }

    def _pause_aware_sleep(self, duration):
        sleeper = getattr(self.window_controller, "pause_aware_sleep", None)
        if callable(sleeper):
            return sleeper(duration)
        time.sleep(duration)
        return True

    def _pause_requested(self):
        checker = getattr(self.window_controller, "is_pause_requested", None)
        try:
            return bool(checker and checker())
        except Exception:
            return False

    def send_webhook_notification(self, event_type, screenshot=None, details=None):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(async_notify_user(event_type, screenshot, details=details or {}))
        finally:
            loop.close()

    def current_target_details(self, extra=None):
        current = self.brawlers_pick_data[0] if self.brawlers_pick_data else {}
        type_to_push = current.get("type", "trophies")
        values = {
            "trophies": self.Trophy_observer.current_trophies,
            "wins": self.Trophy_observer.current_wins,
        }
        details = {
            "brawler": current.get("brawler", ""),
            "started_trophies": self.started_trophies_by_brawler.get(
                str(current.get("brawler", "")).lower(),
                current.get("trophies", 0),
            ),
            "trophies": values.get(type_to_push, self.Trophy_observer.current_trophies),
            "target": current.get("push_until", ""),
            "wins": self.Trophy_observer.current_wins,
            "win_streak": self.Trophy_observer.win_streak,
            "brawlers_left": len(self.brawlers_pick_data),
        }
        if extra:
            details.update(extra)
        return details

    @staticmethod
    def validate_trophies(trophies_string):
        trophies_string = trophies_string.lower()
        while "s" in trophies_string:
            trophies_string = trophies_string.replace("s", "5")
        numbers = ''.join(filter(str.isdigit, trophies_string))

        if not numbers:
            return False

        trophy_value = int(numbers)
        return trophy_value

    @staticmethod
    def _number_or_default(value, default=0):
        try:
            if value == "":
                return default
            return int(value)
        except (TypeError, ValueError):
            return default

    def _prepare_next_push_all_brawler(self, target, type_of_push="trophies"):
        """Remove completed Push All rows and choose the current lowest remaining row.

        Push All queues are built from API trophies at launch, but the queue can
        become stale after each match. Re-sorting here keeps 250/500/750/1000
        targets on the same "least trophies next" behavior the player sees in
        the Brawl Stars brawler menu.
        """
        if not self.brawlers_pick_data:
            return False

        target = self._number_or_default(target, 1000 if type_of_push == "trophies" else 300)
        current_row = self.brawlers_pick_data[0]
        current_row[type_of_push] = self._number_or_default(
            getattr(self.Trophy_observer, f"current_{type_of_push}", current_row.get(type_of_push, 0)),
            current_row.get(type_of_push, 0),
        )
        current_row["win_streak"] = self.Trophy_observer.win_streak

        remaining = self.brawlers_pick_data[1:]
        if type_of_push == "trophies":
            remaining = [
                dict(row)
                for row in remaining
                if self._number_or_default(row.get("trophies", 0), 0)
                < self._number_or_default(row.get("push_until", target), target)
            ]
        else:
            remaining = [
                dict(row)
                for row in remaining
                if self._number_or_default(row.get("wins", 0), 0)
                < self._number_or_default(row.get("push_until", target), target)
            ]

        if not remaining:
            self.brawlers_pick_data = []
            save_brawler_data(self.brawlers_pick_data)
            return False

        if any(row.get("selection_method") == "lowest_trophies" for row in remaining):
            remaining.sort(
                key=lambda row: (
                    self._number_or_default(row.get(type_of_push, 0), 0),
                    str(row.get("brawler", "")),
                )
            )
            for row in remaining:
                row["selection_method"] = "lowest_trophies"
                row["automatically_pick"] = True

        self.brawlers_pick_data = remaining
        next_data = self.brawlers_pick_data[0]
        self.Trophy_observer.change_trophies(self._number_or_default(next_data.get("trophies", 0), 0))
        self.Trophy_observer.current_wins = self._number_or_default(next_data.get("wins", 0), 0)
        self.Trophy_observer.win_streak = self._number_or_default(next_data.get("win_streak", 0), 0)
        save_brawler_data(self.brawlers_pick_data)
        self.api_selection_checks_remaining = 3
        self.force_reselect_current_brawler = False
        return True

    def current_brawler_trophies_for_api(self):
        if not self.brawlers_pick_data:
            return None
        row = self.brawlers_pick_data[0]
        return self._number_or_default(
            getattr(self.Trophy_observer, "current_trophies", row.get("trophies", 0)),
            row.get("trophies", 0),
        )

    @staticmethod
    def _short_error(error):
        text = str(error).replace("\n", " | ")
        return text[:240] + ("..." if len(text) > 240 else "")

    def api_trophies_for_brawler(self, player_data, brawler_name):
        wanted_key = normalize_brawler_name(brawler_name)
        for brawler in player_data.get("brawlers", []):
            if normalize_brawler_name(brawler.get("name", "")) == wanted_key:
                return self._number_or_default(brawler.get("trophies", 0), 0)
        return None

    def fetch_current_brawler_trophies_from_api(self, reason="sync"):
        """Read current brawler trophies from Brawltracker without mutating local state.

        This is important right after a match: Brawltracker can still return the
        pre-match value for a few seconds. If we assign that value before local
        trophy math, the log becomes stale, for example 400 -> 400 after a win.
        """
        if not self.brawlers_pick_data:
            return None
        if self.brawlers_pick_data[0].get("type", "trophies") != "trophies":
            return None
        current_name = self.brawlers_pick_data[0].get("brawler", "")
        try:
            player_data = self.fetch_push_all_player_data(
                force_token_refresh=False,
                current_trophies=self.current_brawler_trophies_for_api(),
            )
        except Exception as e:
            print(f"Could not read current brawler trophies from API during {reason}; using local trophies. {self._short_error(e)}")
            return None
        api_trophies = self.api_trophies_for_brawler(player_data, current_name)
        if api_trophies is None:
            print(f"Could not find {current_name} in Brawltracker response during {reason}; using local trophies.")
            return None
        return api_trophies

    def sync_current_brawler_trophies_from_api(self, reason="sync"):
        api_trophies = self.fetch_current_brawler_trophies_from_api(reason=reason)
        if api_trophies is None:
            return None
        self.brawlers_pick_data[0]["trophies"] = api_trophies
        self.Trophy_observer.change_trophies(api_trophies)
        save_brawler_data(self.brawlers_pick_data)
        return api_trophies

    def confirm_current_brawler_reached_target_from_api(self, target):
        api_trophies = self.sync_current_brawler_trophies_from_api(reason="completion check")
        if api_trophies is None:
            return True
        if api_trophies < self._number_or_default(target, 1000):
            print(
                f"Completion cancelled: Brawltracker shows {api_trophies} trophies, "
                f"target is {target}. Continuing push with parsed trophy value."
            )
            self.stop_after_post_match_rewards = False
            self.completion_notification_sent = False
            return False
        return True

    def update_win_streak_from_result_without_trophy_math(self, game_result):
        if game_result in ("victory", "1st", "2nd"):
            self.Trophy_observer.win_streak += 1
        elif game_result in ("defeat", "4th"):
            self.Trophy_observer.win_streak = 0

    def estimate_trophies_after_result(self, game_result):
        current = self._number_or_default(getattr(self.Trophy_observer, "current_trophies", 0), 0)
        new_trophies = current
        if game_result in getattr(self.Trophy_observer, "_showdown_place_index", {}):
            place_index = self.Trophy_observer._showdown_place_index[game_result]
            delta = self.Trophy_observer.calc_showdown_delta(place_index)
            if game_result in ("1st", "2nd"):
                streak_after = self.Trophy_observer.win_streak + 1
                streak_bonus = min(streak_after - 1, 10) if current < 2000 else 0
                new_trophies = current + delta + streak_bonus
            else:
                new_trophies = current + delta
        elif game_result == "victory":
            base_gain = 0
            for max_trophies, gain in self.Trophy_observer.trophy_win_ranges:
                if float(current) <= float(max_trophies):
                    base_gain = gain * self.Trophy_observer.trophies_multiplier
                    break
            streak_after = self.Trophy_observer.win_streak + 1
            streak_bonus = min(streak_after - 1, 10) if current < 2000 else 0
            new_trophies = current + base_gain + streak_bonus
        elif game_result == "defeat":
            new_trophies = current - self.Trophy_observer.calc_lost_decrement()
        elif game_result == "draw":
            new_trophies = current
        if current >= 1000 and new_trophies < 1000:
            new_trophies = 1000
        return new_trophies

    def verify_selected_brawler_with_parsed_trophies(self, expected_trophies, parsed_trophies):
        remaining = getattr(self, "api_selection_checks_remaining", 3)
        if remaining <= 0:
            return True
        self.api_selection_checks_remaining = remaining - 1
        if parsed_trophies != expected_trophies:
            current_name = self.brawlers_pick_data[0].get("brawler", "") if self.brawlers_pick_data else ""
            print(
                f"Selected brawler check failed for {current_name}: expected "
                f"{expected_trophies}, Brawltracker parsed {parsed_trophies}. Reselecting brawler before next match."
            )
            self.force_reselect_current_brawler = True
            return False
        print(f"Selected brawler check passed: {parsed_trophies} trophies.")
        return True

    def verify_selected_brawler_with_api_after_match(self, expected_trophies):
        if not self.brawlers_pick_data:
            return True
        if self.brawlers_pick_data[0].get("type", "trophies") != "trophies":
            return True
        remaining = getattr(self, "api_selection_checks_remaining", 3)
        if remaining <= 0:
            return True
        self.api_selection_checks_remaining = remaining - 1
        current_name = self.brawlers_pick_data[0].get("brawler", "")
        api_trophies = self.sync_current_brawler_trophies_from_api(reason="first games selection check")
        if api_trophies is None:
            return True
        expected_trophies = self._number_or_default(expected_trophies, api_trophies)
        if api_trophies != expected_trophies:
            print(
                f"Selected brawler check failed for {current_name}: local expected "
                f"{expected_trophies}, Brawltracker parsed {api_trophies}. Reselecting brawler before next match."
            )
            self.force_reselect_current_brawler = True
            return False
        print(f"Selected brawler check passed for {current_name}: {api_trophies} trophies.")
        return True

    def refresh_push_all_trophies_from_api(self):
        if not self.brawlers_pick_data:
            return False
        if self.brawlers_pick_data[0].get("type", "trophies") != "trophies":
            return False

        # Re-sync trophies from the API on EVERY trophies push start, including
        # manual queues with several brawlers. Only the automatic
        # "lowest trophies" queue additionally re-sorts/drops rows.
        uses_lowest = any(
            row.get("selection_method") == "lowest_trophies"
            for row in self.brawlers_pick_data
        )

        old_front_brawler = self.brawlers_pick_data[0].get("brawler")
        try:
            player_data = self.fetch_push_all_player_data(
                force_token_refresh=False,
                current_trophies=self.current_brawler_trophies_for_api(),
            )
        except RuntimeError as e:
            if "accessDenied" not in str(e):
                print(f"Push All API trophy refresh failed; using local trophies. {self._short_error(e)}")
                return False
            try:
                print("Push All API token was rejected; refreshing token for current public IP and retrying.")
                player_data = self.fetch_push_all_player_data(
                    force_token_refresh=True,
                    current_trophies=self.current_brawler_trophies_for_api(),
                )
            except Exception as retry_error:
                print(f"Push All API trophy refresh failed after token refresh; using local trophies. {self._short_error(retry_error)}")
                return False
        except Exception as e:
            print(f"Push All API trophy refresh failed; using local trophies. {e}")
            return False

        trophies_by_brawler = {
            normalize_brawler_name(brawler.get("name", "")): int(brawler.get("trophies", 0))
            for brawler in player_data.get("brawlers", [])
        }
        target = self._number_or_default(self.brawlers_pick_data[0].get("push_until", 1000), 1000)

        if not uses_lowest:
            # Manual multi-brawler queue: only refresh each row's trophy count
            # from the API and update the current brawler's observed trophies.
            # Keep the user's order and selection settings; start_game handles
            # advancing to the next brawler once the target is reached.
            changed = False
            for row in self.brawlers_pick_data:
                key = normalize_brawler_name(row.get("brawler", ""))
                if key not in trophies_by_brawler:
                    continue
                api_trophies = trophies_by_brawler[key]
                if row.get("trophies") != api_trophies:
                    row["trophies"] = api_trophies
                    changed = True
            front_trophies = self._number_or_default(
                self.brawlers_pick_data[0].get("trophies", 0), 0
            )
            if getattr(self.Trophy_observer, "current_trophies", None) != front_trophies:
                self.Trophy_observer.change_trophies(front_trophies)
                changed = True
            if changed:
                print("Push All API trophies refreshed for the current queue.")
                save_brawler_data(self.brawlers_pick_data)
            return changed

        changed = False
        refreshed_rows = []
        for row in self.brawlers_pick_data:
            key = normalize_brawler_name(row.get("brawler", ""))
            refreshed_row = dict(row)
            if key in trophies_by_brawler:
                api_trophies = trophies_by_brawler[key]
                if refreshed_row.get("trophies") != api_trophies:
                    refreshed_row["trophies"] = api_trophies
                    changed = True
            if self._number_or_default(refreshed_row.get("trophies", 0), 0) < target:
                refreshed_rows.append(refreshed_row)

        current_row = next(
            (row for row in refreshed_rows if row.get("brawler") == old_front_brawler),
            None,
        )
        remaining_rows = [
            row for row in refreshed_rows
            if row.get("brawler") != old_front_brawler
        ]

        if current_row is not None:
            remaining_rows.sort(
                key=lambda row: (
                    self._number_or_default(row.get("trophies", 0), 0),
                    str(row.get("brawler", "")),
                )
            )
            refreshed_rows = [current_row] + remaining_rows
            self.push_all_needs_selection = False
        else:
            refreshed_rows = remaining_rows
            self.push_all_needs_selection = bool(refreshed_rows)

        if refreshed_rows:
            refreshed_rows[0]["automatically_pick"] = False
            refreshed_rows[0]["selection_method"] = "lowest_trophies"
            for row in refreshed_rows[1:]:
                if row.get("automatically_pick") is not True:
                    changed = True
                row["automatically_pick"] = True
                row["selection_method"] = "lowest_trophies"

        old_order = [row.get("brawler") for row in self.brawlers_pick_data]
        new_order = [row.get("brawler") for row in refreshed_rows]
        if new_order != old_order:
            changed = True

        if not refreshed_rows:
            self.brawlers_pick_data = []
            save_brawler_data(self.brawlers_pick_data)
            print("Push All API trophies refreshed: all brawlers reached target.")
            return True

        if len(refreshed_rows) != len(self.brawlers_pick_data):
            changed = True

        self.brawlers_pick_data = refreshed_rows

        current_trophies = self._number_or_default(self.brawlers_pick_data[0].get("trophies", 0), 0)
        if getattr(self.Trophy_observer, "current_trophies", None) != current_trophies:
            self.Trophy_observer.change_trophies(current_trophies)
            changed = True

        if changed:
            if self.push_all_needs_selection:
                print("Push All API trophies refreshed; current brawler reached target, selecting next lowest.")
            else:
                print("Push All API trophies refreshed; keeping current brawler until target.")
            save_brawler_data(self.brawlers_pick_data)
        return changed

    def fetch_push_all_player_data(self, force_token_refresh=False, current_trophies=None):
        api_config = load_brawl_stars_api_config("cfg/brawl_stars_api.toml", force_refresh=force_token_refresh)
        return fetch_brawl_stars_player(
            api_config.get("api_token", "").strip(),
            api_config.get("player_tag", "").strip(),
            int(api_config.get("timeout_seconds", 15)),
            current_trophies=current_trophies,
        )

    def start_game(self):
        print("Lobby detected; preparing to start match.")
        if getattr(self, "stop_after_post_match_rewards", False):
            print("Post-match rewards cleared; stopping after completed target.")
            if os.path.exists("cfg/latest_brawler_data.json"):
                os.remove("cfg/latest_brawler_data.json")
            self.window_controller.keys_up(list("wasd"))
            self.window_controller.close()
            sys.exit(0)
        self.push_all_needs_selection = False
        self.refresh_push_all_trophies_from_api()
        if not self.brawlers_pick_data:
            print("Bot stopping: all Push All targets completed.")
            self.window_controller.keys_up(list("wasd"))
            self.window_controller.close()
            sys.exit(0)
        values = {
            "trophies": self.Trophy_observer.current_trophies,
            "wins": self.Trophy_observer.current_wins
        }

        type_of_push = self.brawlers_pick_data[0]['type']
        if type_of_push not in values:
            type_of_push = "trophies"
        value = values[type_of_push]
        if value == "" and type_of_push == "wins":
            value = 0
        push_current_brawler_till = self.brawlers_pick_data[0]['push_until']
        if push_current_brawler_till == "" and type_of_push == "wins":
            push_current_brawler_till = 300
        if push_current_brawler_till == "" and type_of_push == "trophies":
            push_current_brawler_till = 1000

        if value >= push_current_brawler_till and type_of_push == "trophies":
            if not self.confirm_current_brawler_reached_target_from_api(push_current_brawler_till):
                value = self.Trophy_observer.current_trophies

        if value >= push_current_brawler_till:
            if len(self.brawlers_pick_data) <= 1:
                print("Brawler reached required trophies/wins. No more brawlers selected for pushing in the menu. "
                      "Bot will now pause itself until closed.", value, push_current_brawler_till)
                screenshot = self.window_controller.screenshot()
                self.send_webhook_notification(
                    "completed",
                    screenshot,
                    self.current_target_details({"target": push_current_brawler_till}),
                )
                print("Bot stopping: all targets completed with no more brawlers.")
                self.window_controller.keys_up(list("wasd"))
                self.window_controller.close()
                sys.exit(0)
            completed_brawler = self.brawlers_pick_data[0]["brawler"]
            screenshot = self.window_controller.screenshot()
            self.send_webhook_notification(
                "brawler_complete",
                screenshot,
                self.current_target_details({
                    "brawler": completed_brawler,
                    "target": push_current_brawler_till,
                    "brawlers_left": max(0, len(self.brawlers_pick_data) - 1),
                }),
            )
            if not self._prepare_next_push_all_brawler(push_current_brawler_till, type_of_push):
                print("Brawler reached required trophies/wins. No remaining brawlers are below the Push All target.")
                self.send_webhook_notification(
                    "completed",
                    screenshot,
                    self.current_target_details({"target": push_current_brawler_till}),
                )
                print("Bot stopping: all Push All targets completed.")
                self.window_controller.keys_up(list("wasd"))
                self.window_controller.close()
                sys.exit(0)
            if self.brawlers_pick_data[0]["automatically_pick"]:
                print("Picking next automatically picked brawler")
                screenshot = self.window_controller.screenshot()
                current_state = get_state(screenshot)
                if current_state != "lobby":
                    print("Trying to reach the lobby to switch brawler")

                max_attempts = 30
                attempts = 0
                while current_state != "lobby" and attempts < max_attempts:
                    self.window_controller.press_key("Q")
                    print("Pressed Q to return to lobby")
                    self._pause_aware_sleep(1)
                    screenshot = self.window_controller.screenshot()
                    current_state = get_state(screenshot)
                    attempts += 1
                if attempts >= max_attempts:
                    print("Failed to reach lobby after max attempts")
                else:
                    selection_method = self.brawlers_pick_data[0].get("selection_method", "named_brawler")
                    if selection_method == "lowest_trophies":
                        selected = self.Lobby_automation.select_lowest_trophy_brawler()
                    else:
                        next_brawler_name = self.brawlers_pick_data[0]['brawler']
                        self.Lobby_automation.select_brawler(next_brawler_name)
                        selected = True
                    if not selected:
                        print("Could not confirm the next brawler selection reached lobby; delaying match start.")
                        self.window_controller.keys_up(list("wasd"))
                        return
            else:
                print("Next brawler is in manual mode, waiting 10 seconds to let user switch.")

        elif self.push_all_needs_selection:
            print("Push All queue changed from API; selecting the new lowest trophy brawler.")
            selected = self.Lobby_automation.select_lowest_trophy_brawler()
            if not selected:
                print("Could not confirm the API-refreshed brawler selection reached lobby; delaying match start.")
                self.window_controller.keys_up(list("wasd"))
                return

        if getattr(self, "force_reselect_current_brawler", False) and self.brawlers_pick_data:
            current_brawler = self.brawlers_pick_data[0].get("brawler", "")
            print(f"Reselecting {current_brawler} after API selection check before starting next match.")
            selection_method = self.brawlers_pick_data[0].get("selection_method", "named_brawler")
            if selection_method == "lowest_trophies":
                selected = self.Lobby_automation.select_lowest_trophy_brawler()
            else:
                selected = self.Lobby_automation.select_brawler(current_brawler)
                if selected is None:
                    selected = True
            if not selected:
                print("Could not confirm brawler reselection; delaying match start.")
                self.window_controller.keys_up(list("wasd"))
                return
            self.force_reselect_current_brawler = False
            self._pause_aware_sleep(0.35)
            post_select_state = get_state(self.window_controller.screenshot())
            if post_select_state == "shop":
                print("Brawler reselection opened shop; closing it before starting match.")
                self.quit_shop()
                return
            if post_select_state != "lobby":
                print(f"Brawler reselection ended in {post_select_state}; delaying match start until lobby is visible.")
                self.window_controller.stop_gameplay_controls()
                return

        # Final lobby sync: right before pressing Q, parse trophies from Brawltracker.
        # If Brawltracker is unavailable, keep the locally calculated value as plan B.
        if self.brawlers_pick_data and self.brawlers_pick_data[0].get("type", "trophies") == "trophies":
            parsed_trophies = self.sync_current_brawler_trophies_from_api(reason="lobby start before Q")
            if parsed_trophies is not None:
                target = self._number_or_default(self.brawlers_pick_data[0].get("push_until", 1000), 1000)
                print(f"Lobby trophy sync before match start: {parsed_trophies}/{target}")
                if parsed_trophies >= target:
                    print("Current brawler reached target after lobby sync; not starting a new match.")
                    self.start_game()
                    return

        current_start_state = get_state(self.window_controller.screenshot())
        if current_start_state == "shop":
            print("Shop detected before match start; closing it instead of pressing Start/Q.")
            self.quit_shop()
            return
        if current_start_state != "lobby":
            print(f"Not starting match because current state is {current_start_state}, not lobby.")
            self.window_controller.stop_gameplay_controls()
            return

        # q btn is over the start btn
        self.window_controller.stop_gameplay_controls()
        self.window_controller.press_key("Q")
        print("Pressed Q to start a match")


    def play_again_on_win_enabled(self):
        try:
            bot_config = load_toml_as_dict("cfg/bot_config.toml")
            return str(bot_config.get("play_again_on_win", "no")).lower() in ("yes", "true", "1", "on")
        except Exception:
            return False

    @staticmethod
    def is_win_result(game_result):
        return game_result in ("victory", "1st", "2nd")

    def find_play_again_button_center(self, screenshot):
        """Find the green/blue Play Again button on the post-match screen.

        This is more reliable than fixed coordinates because the result screen
        layout changes after rewards, events, aspect ratio scaling and language.
        We scan the lower part of the screen and choose the strongest button-like
        blob on the right/center side. Screenshot from window_controller is RGB.
        """
        if screenshot is None or screenshot.size == 0:
            return None
        h, w = screenshot.shape[:2]
        # Do not scan the middle of the victory screen. Large green/blue
        # decorative panels there can look like buttons and caused clicks around
        # 970,580 on 1920x1080. Play Again is always in the lower action bar.
        y0, y1 = int(h * 0.76), int(h * 0.995)
        x0, x1 = int(w * 0.46), int(w * 0.995)
        crop = screenshot[y0:y1, x0:x1]
        if crop.size == 0:
            return None

        # Try both RGB and BGR interpretation. Live screenshots are usually RGB,
        # but some capture paths return BGR.
        candidates = []
        ch, cw = crop.shape[:2]
        for conversion in (cv2.COLOR_RGB2HSV, cv2.COLOR_BGR2HSV):
            hsv = cv2.cvtColor(crop, conversion)
            # PLAY AGAIN is usually green. Some post-result actions can be blue, so
            # accept both but score green/right-side candidates higher.
            green = cv2.inRange(hsv, np.array((38, 70, 80), np.uint8), np.array((88, 255, 255), np.uint8))
            blue = cv2.inRange(hsv, np.array((88, 70, 80), np.uint8), np.array((125, 255, 255), np.uint8))
            mask = cv2.bitwise_or(green, blue)
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            white = cv2.inRange(hsv, np.array((0, 0, 150), np.uint8), np.array((179, 100, 255), np.uint8))
            for contour in contours:
                area = cv2.contourArea(contour)
                bx, by, bw, bh = cv2.boundingRect(contour)
                if bw <= 0 or bh <= 0:
                    continue
                if area < max(900, ch * cw * 0.010):
                    continue
                if bw < cw * 0.12 or bh < ch * 0.18:
                    continue
                if area / max(1, bw * bh) < 0.45:
                    continue
                cx = bx + bw / 2
                # Ignore far-left buttons such as EXIT and any middle-screen panels.
                # In absolute screen coordinates this means roughly right half.
                if x0 + cx < w * 0.54:
                    continue
                white_ratio = cv2.countNonZero(white[by:by + bh, bx:bx + bw]) / max(1, bw * bh)
                if white_ratio < 0.006:
                    continue
                green_ratio = cv2.countNonZero(green[by:by + bh, bx:bx + bw]) / max(1, bw * bh)
                score = area + cx * 2 + green_ratio * 2500 + white_ratio * 1200
                candidates.append((score, bx, by, bw, bh))

        if not candidates:
            return None
        _, bx, by, bw, bh = max(candidates, key=lambda item: item[0])
        return int(x0 + bx + bw / 2), int(y0 + by + bh / 2)

    def lobby_config_value(self, key, default=None):
        if key in self.lobby_config:
            return self.lobby_config.get(key, default)
        for value in self.lobby_config.values():
            if isinstance(value, dict) and key in value:
                return value.get(key, default)
        return default

    def click_end_screen_exit_button(self, screenshot=None, log=True):
        """Leave the result screen without pressing Play Again.

        Play Again has a separate configured coordinate. When the feature is
        disabled, use the left/lower Exit/Continue button instead of Q, because
        Q may overlap Play Again on some key layouts.
        """
        if screenshot is None:
            try:
                screenshot = self.window_controller.screenshot()
            except Exception:
                screenshot = None
        x = int(float(self.lobby_config_value("end_screen_exit_x", 1690)))
        y = int(float(self.lobby_config_value("end_screen_exit_y", 990)))
        wait_seconds = self._number_or_default(self.lobby_config_value("end_screen_exit_wait_seconds", 0.35), 0.35)
        post_click_wait = self._number_or_default(self.lobby_config_value("end_screen_exit_post_click_wait_seconds", 3.0), 3.0)
        if wait_seconds > 0:
            self._pause_aware_sleep(wait_seconds)
        self.window_controller.stop_gameplay_controls()
        self.window_controller.click(x, y, delay=0.08, already_include_ratio=False)
        self.tap_with_adb_fallback(x, y, screenshot_shape=(screenshot.shape if screenshot is not None else (1080, 1920, 3)))
        if log:
            print(f"Clicked end-screen Exit/Continue coordinates: {x},{y}. Waiting {post_click_wait:.1f}s for post-match transition.")
            if post_click_wait > 0:
                self._pause_aware_sleep(post_click_wait)

    def click_play_again_button(self, screenshot=None):
        """Use the mapped R action for Play Again instead of coordinate clicks.

        In the emulator control layout, R is placed over the Play Again action
        button. On result screens this is safer than trying to click the visual
        Play Again button by coordinates, because the button position changes
        across result/reward screens and caused missed clicks.
        """
        wait_seconds = self._number_or_default(self.lobby_config_value("play_again_wait_seconds", 5), 5)
        if wait_seconds > 0:
            print(f"Waiting {wait_seconds:.1f}s before Play Again/Continue.")
            self._pause_aware_sleep(wait_seconds)

        self.window_controller.keys_up(list("wasd"))
        configured_x = self.lobby_config_value("play_again_x", None)
        configured_y = self.lobby_config_value("play_again_y", None)
        try:
            if configured_x is not None and configured_y is not None:
                x = int(float(configured_x))
                y = int(float(configured_y))
                self.window_controller.click(x, y, delay=0.10, already_include_ratio=False)
                self.tap_with_adb_fallback(x, y, screenshot_shape=(screenshot.shape if screenshot is not None else (1080, 1920, 3)))
                print(f"Clicked configured Play Again coordinates: {x},{y}.")
                return
        except Exception as exc:
            print(f"Configured Play Again coordinates are invalid, using R: {exc}")

        self.window_controller.press_key("R", delay=0.10)
        print("Pressed R for Play Again/Continue.")

    def continue_play_again_flow(self, initial_state=None, max_seconds=22):
        """After a win, keep clearing reward/result screens until next match starts.

        Some Brawl Stars result flows leave the end_* state after one click and show
        trophy rewards, star drops, YOU GOT screens, or even return to lobby. The old
        code stopped as soon as state was no longer end_*, so Play Again could be
        lost. This method keeps the flow alive and falls back to starting from lobby.
        """
        started = time.time()
        current_state = initial_state
        while time.time() - started < max_seconds:
            screenshot = self.window_controller.screenshot()
            current_state = get_state(screenshot) if current_state is None else current_state

            if current_state in ("match_making", "match"):
                print(f"Play Again flow succeeded: {current_state}.")
                return True

            if current_state == "lobby":
                print("Play Again returned to lobby; starting next match from lobby as fallback.")
                self.start_game()
                return True

            if current_state == "star_drop":
                self.handle_star_drop()
            elif current_state == "you_got":
                self.handle_you_got()
            elif current_state == "prestige_reward":
                self.handle_prestige_reward()
            elif current_state == "popup":
                self.close_pop_up()
            elif current_state == "trophy_reward":
                self.window_controller.press_key("Q")
            else:
                self.click_play_again_button(screenshot)

            self._pause_aware_sleep(max(0.45, self.end_screen_dismiss_delay))
            current_state = None

        print(f"Play Again flow timed out in state: {current_state}. Normal state loop will continue.")
        return False

    def should_use_play_again_after_match(self, game_result, type_to_push, value, target):
        if not self.play_again_on_win_enabled():
            return False
        if not self.is_win_result(game_result):
            return False
        if getattr(self, "stop_after_post_match_rewards", False):
            return False
        try:
            return self._number_or_default(value, 0) < self._number_or_default(target, 1000 if type_to_push == "trophies" else 300)
        except Exception:
            return True
    def advance_to_next_brawler_after_prestige(self):
        if not self.brawlers_pick_data:
            return False
        current_brawler = self.brawlers_pick_data[0].get("brawler", "current")
        print(f"Prestige reward detected for {current_brawler}; treating current brawler as completed.")
        self.brawlers_pick_data[0]["trophies"] = max(1000, int(self.brawlers_pick_data[0].get("trophies") or 0))
        self.brawlers_pick_data[0]["push_until"] = max(1000, int(self.brawlers_pick_data[0].get("push_until") or 1000))

        if len(self.brawlers_pick_data) <= 1:
            print("Prestige reward reached, but no next brawler is queued.")
            self.stop_after_post_match_rewards = True
            save_brawler_data(self.brawlers_pick_data)
            return False

        self.brawlers_pick_data.pop(0)
        next_data = self.brawlers_pick_data[0]
        self.Trophy_observer.change_trophies(next_data.get("trophies", 0))
        self.Trophy_observer.current_wins = next_data.get("wins", 0) if next_data.get("wins", "") != "" else 0
        self.Trophy_observer.win_streak = next_data.get("win_streak", 0)
        save_brawler_data(self.brawlers_pick_data)
        return True

    def read_lobby_trophies_from_screenshot(self, screenshot):
        height, width = screenshot.shape[:2]
        width_ratio = width / 1920
        height_ratio = height / 1080
        x1 = int(700 * width_ratio)
        y1 = int(58 * height_ratio)
        x2 = int(990 * width_ratio)
        y2 = int(165 * height_ratio)
        crop = screenshot[y1:y2, x1:x2]
        if crop.size == 0:
            return None

        try:
            crop = cv2.resize(crop, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
            texts = extract_text_strings(crop)
        except Exception as e:
            print(f"Could not OCR lobby trophies after reward: {e}")
            return None

        for text in texts:
            value = self.validate_trophies(text)
            if value is not False and 0 <= value <= 5000:
                return value
        print(f"Could not read lobby trophies after reward from OCR: {texts}")
        return None

    def wait_for_lobby_after_reward(self, max_attempts=30):
        screenshot = self.window_controller.screenshot()
        current_state = get_state(screenshot)
        attempts = 0
        while current_state != "lobby" and attempts < max_attempts:
            self.window_controller.press_key("Q")
            self._pause_aware_sleep(1.0)
            screenshot = self.window_controller.screenshot()
            current_state = get_state(screenshot)
            attempts += 1
        return screenshot if current_state == "lobby" else None

    def handle_star_drop(self):
        screenshot = self.window_controller.screenshot()
        screenshot_bgr = cv2.cvtColor(screenshot, cv2.COLOR_RGB2BGR)
        drop_type = get_star_drop_type(screenshot_bgr)
        if drop_type is None:
            return

        print(f"{drop_type.title()} star drop detected; opening by template.")
        self.window_controller.keys_up(list("wasd"))
        current_height, current_width = screenshot.shape[:2]
        width_ratio = current_width / 1920
        height_ratio = current_height / 1080
        x = int(965 * width_ratio)
        y = int(525 * height_ratio)
        if drop_type in ("angelic", "demonic"):
            for _ in range(3):
                self.window_controller.click(x, y, delay=0.45)
                self._pause_aware_sleep(0.2)
        else:
            for _ in range(5):
                self.window_controller.click(x, y, delay=0.04)
                self._pause_aware_sleep(0.08)

    def handle_you_got(self):
        # "YOU GOT: ..." reward overlays are dismissed by tapping anywhere.
        # Tap the centre (like star drops) and also send the Q dismiss key.
        self.window_controller.keys_up(list("wasd"))
        wr = self.window_controller.width_ratio
        hr = self.window_controller.height_ratio
        print("YOU GOT reward screen detected; dismissing.")
        #self.window_controller.click(int(965 * wr), int(525 * hr), delay=0.05)
        self._pause_aware_sleep(0.2)
        self.window_controller.press_key("F")
        self._pause_aware_sleep(0.2)

    def handle_prestige_reward(self):
        screenshot = self.window_controller.screenshot()
        screenshot_bgr = cv2.cvtColor(screenshot, cv2.COLOR_RGB2BGR)
        next_button_center = get_prestige_next_button_center(screenshot_bgr)
        if next_button_center is None or not is_in_prestige_reward(screenshot_bgr):
            print("Prestige reward state ignored; NEXT button was not confirmed.")
            return

        print("Prestige reward screen detected; clicking NEXT.")
        self.window_controller.keys_up(list("wasd"))
        self.window_controller.click(*next_button_center)
        self._pause_aware_sleep(1.0)

        lobby_screenshot = self.wait_for_lobby_after_reward()
        if lobby_screenshot is None:
            print("Could not reach lobby after reward; will retry from normal state loop.")
            return

        lobby_trophies = self.read_lobby_trophies_from_screenshot(lobby_screenshot)
        if lobby_trophies is not None and self.brawlers_pick_data:
            print(f"Lobby trophies after reward: {lobby_trophies}")
            self.Trophy_observer.change_trophies(lobby_trophies)
            self.brawlers_pick_data[0]["trophies"] = lobby_trophies
            save_brawler_data(self.brawlers_pick_data)

        # ВАЖНО: смена бойца / "пуш завершён" решается ТОЛЬКО по трофеям из API
        # + математике в start_game(), а НЕ по этому визуальному экрану.
        # Раньше ложный prestige_reward принудительно переключал бойца
        # ("пуш завершён", хотя цель не достигнута). Теперь просто закрываем
        # экран и обновляем трофеи из API — решение примет start_game().
        if lobby_trophies is None:
            print("Could not read lobby trophies after prestige; will refresh from API.")
        try:
            self.refresh_push_all_trophies_from_api()
        except Exception as e:
            print(f"Trophy refresh after prestige failed; relying on local trophies. {e}")
        self.window_controller.press_key("Q")
        return

    def end_game(self):
        screenshot = self.window_controller.screenshot()

        found_game_result = False
        current_state = get_state(screenshot)
        button_pressed = False
        play_again_requested = False
        end_screen_time = time.time()

        # If this is a re-entry on the same lingering end-of-match screen,
        # skip recording and just keep trying to dismiss it.
        current_result = current_state.split("_", 1)[1] if current_state.startswith("end_") else None
        already_recorded = current_result is not None and self.active_end_result == current_result
        stats_recorded = already_recorded
        if already_recorded:
            found_game_result = current_result
            print(f"end_game: re-entry on '{current_state}', skipping trophy update")

        # Dismiss non-Play-Again end screens immediately.
        # API trophy checks and webhook sending can take a few seconds, and previously
        # the bot waited for those tasks before pressing the result-screen button.
        # This made the bot sit on end_victory/end_defeat for too long.
        immediate_dismiss_sent = False
        end_dismiss_press_count = 0
        last_end_dismiss_press_time = 0.0
        if current_result is not None:
            play_again_possible = self.play_again_on_win_enabled() and self.is_win_result(current_result)
            if not play_again_possible:
                self.click_end_screen_exit_button()
                immediate_dismiss_sent = True
                end_dismiss_press_count = 1
                last_end_dismiss_press_time = time.time()
                button_pressed = True
                print(f"End screen {current_state} detected; clicked Exit/Continue immediately while processing stats.")

        while current_state.startswith("end") and time.time() - end_screen_time < 25:
            if not stats_recorded:
                found_game_result = current_state.split("_")[1]
                current_brawler = self.brawlers_pick_data[0]['brawler']
                type_to_push = self.brawlers_pick_data[0]['type']
                if type_to_push not in ("trophies", "wins"):
                    type_to_push = "trophies"

                parsed_trophies = None
                expected_trophies = None
                old_trophies = self.Trophy_observer.current_trophies
                trophies_unchanged_after_win = False
                if type_to_push == "trophies":
                    expected_trophies = self.estimate_trophies_after_result(found_game_result)
                    # Read the API value only for verification. Do NOT assign it before
                    # local trophy math, because Brawltracker may still return the
                    # pre-match value and produce stale logs like 400 -> 400.
                    parsed_trophies = self.fetch_current_brawler_trophies_from_api(reason="post-match verification")

                self.Trophy_observer.add_trophies(found_game_result, current_brawler)

                if type_to_push == "trophies" and parsed_trophies is not None:
                    local_after = self.Trophy_observer.current_trophies
                    if parsed_trophies == old_trophies:
                        if self.is_win_result(found_game_result) and local_after == old_trophies:
                            trophies_unchanged_after_win = True
                            self.force_reselect_current_brawler = True
                            print(
                                f"Win was detected, but local and API trophies did not change: "
                                f"{old_trophies} -> {parsed_trophies}. "
                                "Forcing brawler reselection before the next match."
                            )
                        else:
                            print(
                                f"Brawltracker trophies are still stale after match: "
                                f"{old_trophies} -> {parsed_trophies}. Keeping local result {local_after}."
                            )
                    elif parsed_trophies == local_after:
                        print(f"Brawltracker trophy verification passed: {old_trophies} -> {parsed_trophies}.")
                    else:
                        print(
                            f"Brawltracker trophy mismatch after match: API {old_trophies} -> {parsed_trophies}, "
                            f"local expected {local_after}. Keeping local value until next lobby sync."
                        )
                        self.verify_selected_brawler_with_parsed_trophies(expected_trophies, parsed_trophies)
                elif type_to_push == "trophies":
                    print("Brawltracker unavailable; used local trophy calculation.")

                self.Trophy_observer.add_win(found_game_result)
                self.adaptive_brain.record_result(found_game_result)
                self.time_since_last_stat_change = time.time()
                self.last_recorded_result = found_game_result
                self.last_recorded_result_time = time.time()
                self.active_end_result = found_game_result
                stats_recorded = True
                values = {
                    "trophies": self.Trophy_observer.current_trophies,
                    "wins": self.Trophy_observer.current_wins
                }
                value = values[type_to_push]
                self.brawlers_pick_data[0][type_to_push] = value
                self.brawlers_pick_data[0]['win_streak'] = self.Trophy_observer.win_streak
                save_brawler_data(self.brawlers_pick_data)
                self.send_webhook_notification(
                    "match",
                    screenshot,
                    self.current_target_details({
                        "result": found_game_result,
                        "target": self.brawlers_pick_data[0].get("push_until", ""),
                    }),
                )
                push_current_brawler_till = self.brawlers_pick_data[0]['push_until']

                if value == "" and type_to_push == "wins":
                    value = 0
                if push_current_brawler_till == "" and type_to_push == "wins":
                    push_current_brawler_till = 300
                if push_current_brawler_till == "" and type_to_push == "trophies":
                    push_current_brawler_till = 1000

                if type_to_push == "trophies":
                    if parsed_trophies is None:
                        self.verify_selected_brawler_with_api_after_match(value)
                    value = self.Trophy_observer.current_trophies

                if value >= push_current_brawler_till and type_to_push == "trophies":
                    if not self.confirm_current_brawler_reached_target_from_api(push_current_brawler_till):
                        value = self.Trophy_observer.current_trophies

                if value >= push_current_brawler_till:
                    if len(self.brawlers_pick_data) <= 1:
                        print(
                            "Brawler reached required trophies/wins. No more brawlers selected for pushing in the menu. "
                            "Bot will finish reward screens before stopping.")
                        self.stop_after_post_match_rewards = True
                        if not getattr(self, "completion_notification_sent", False):
                            screenshot = self.window_controller.screenshot()
                            self.send_webhook_notification(
                                "completed",
                                screenshot,
                                self.current_target_details({
                                    "result": found_game_result,
                                    "target": push_current_brawler_till,
                                }),
                            )
                            self.completion_notification_sent = True

                if trophies_unchanged_after_win:
                    play_again_requested = False
                    print("Play Again skipped because trophies did not change after a win; returning to lobby to reselect brawler.")
                elif self.should_use_play_again_after_match(
                    found_game_result,
                    type_to_push,
                    value,
                    push_current_brawler_till,
                ):
                    play_again_requested = True
                    print("Play Again On Win is enabled; trying to start the next match from the end screen.")
            
            # Keep pressing the dismiss key on every iteration until the
            # end-of-match screens give way. One press is rarely enough in
            # showdown: after the place screen there can be star drops,
            # trophy rewards, and offers to dismiss.
            if play_again_requested:
                self.click_play_again_button(screenshot)
            else:
                now = time.time()
                # Some result screens need two or more Q presses: one to clear the
                # result banner and another to close the following reward/continue
                # layer. Keep pressing Q at a controlled interval while the state is
                # still end_*, instead of pressing once and waiting up to 25 seconds.
                if (not immediate_dismiss_sent) or (
                    end_dismiss_press_count < 6
                    and now - last_end_dismiss_press_time >= max(0.35, self.end_screen_dismiss_delay)
                ):
                    self.click_end_screen_exit_button(screenshot, log=False)
                    end_dismiss_press_count += 1
                    last_end_dismiss_press_time = now
                    button_pressed = True
                    immediate_dismiss_sent = True
                    if end_dismiss_press_count == 1:
                        print("Dismissing end screen with configured Exit/Continue button.")
                    elif end_dismiss_press_count == 6:
                        print("End screen still visible after 6 dismiss attempts.")
                else:
                    self.window_controller.stop_gameplay_controls()

            self._pause_aware_sleep(self.end_screen_dismiss_delay)
            screenshot = self.window_controller.screenshot()
            current_state = get_state(screenshot)
            if play_again_requested and not current_state.startswith("end"):
                self.continue_play_again_flow(initial_state=current_state)
                return

        if play_again_requested:
            self.continue_play_again_flow(initial_state=current_state)
            return

        if current_state == "match":
            print("Game result dismissed; waiting for post-match transition.")
        else:
            print("Game has ended", current_state)

    def quit_shop(self):
        now = time.time()
        if now - getattr(self, "last_shop_exit_time", 0.0) < 0.8:
            return
        self.last_shop_exit_time = now
        self.window_controller.stop_gameplay_controls()
        print("Shop detected; closing shop/back screen.")

        # Android back is the safest way to leave shop-like screens across
        # emulator profiles. Keep coordinate fallbacks for layouts where back is
        # intercepted or unavailable.
        try:
            device = getattr(self.window_controller, "device", None)
            if device is not None:
                device.shell("input keyevent 4")
                self._pause_aware_sleep(0.15)
        except Exception as exc:
            print(f"Android BACK failed while closing shop: {exc}")

        # Fallbacks: upper-left back button and upper-right close button zones.
        try:
            self.window_controller.click(100 * self.window_controller.width_ratio, 60 * self.window_controller.height_ratio, delay=0.05)
            self.window_controller.click(1840 * self.window_controller.width_ratio, 80 * self.window_controller.height_ratio, delay=0.05)
        except Exception as exc:
            print(f"Coordinate fallback failed while closing shop: {exc}")

    def close_pop_up(self):
        screenshot = self.window_controller.screenshot()
        team_invite_reject = get_team_invite_reject_button_center(screenshot, image_is_rgb=True)
        if team_invite_reject:
            now = time.time()
            if now - self.last_team_invite_reject_time < 0.6:
                return
            self.last_team_invite_reject_time = now
            print("Team invite popup detected; rejecting invite.")
            self.window_controller.keys_up(list("wasd"))
            self.window_controller.click(*team_invite_reject, delay=0.08)
            self.tap_with_adb_fallback(*team_invite_reject, screenshot_shape=screenshot.shape)
            return
        continue_button = get_continue_button_center(screenshot, image_is_rgb=True)
        if continue_button:
            print("New-content popup detected; pressing CONTINUE.")
            self.window_controller.keys_up(list("wasd"))
            self.window_controller.click(*continue_button, delay=0.08)
            self.tap_with_adb_fallback(*continue_button, screenshot_shape=screenshot.shape)
            return
        event_close = (
            get_event_info_close_button_center(screenshot, image_is_rgb=True)
            or get_event_info_close_button_center(screenshot, image_is_rgb=False)
        )
        if event_close:
            print("Event info popup detected; closing it.")
            self.window_controller.keys_up(list("wasd"))
            self.window_controller.click(*event_close, delay=0.08)
            self.tap_with_adb_fallback(*event_close, screenshot_shape=screenshot.shape)
            return
        if self.close_popup_icon is None:
            self.close_popup_icon = load_image("images/states/close_popup.png", self.window_controller.scale_factor)
        popup_location = find_template_center(screenshot, self.close_popup_icon)
        if popup_location:
            self.window_controller.click(*popup_location)

    def tap_with_adb_fallback(self, x, y, screenshot_shape=None):
        if self._pause_requested():
            return False
        try:
            device = getattr(self.window_controller, "device", None)
            if device is None:
                return False
            target_x = x
            target_y = y
            if screenshot_shape is not None:
                frame_h, frame_w = screenshot_shape[:2]
                size = device.window_size()
                target_x = x * (size.width / max(1, frame_w))
                target_y = y * (size.height / max(1, frame_h))
            device.shell(f"input tap {int(target_x)} {int(target_y)}")
            return True
        except Exception as e:
            print(f"ADB fallback tap failed: {e}")
            return False

    def do_state(self, state, data=None):
        if self._pause_requested():
            return
        if not str(state).startswith("end"):
            self.active_end_result = None
        if data is not None:
            self.states[state](data)
            return
        self.states[state]()
