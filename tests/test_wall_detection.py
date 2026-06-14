import unittest

from control.play import Play


class TestWallDetectionPostprocess(unittest.TestCase):
    def make_play(self):
        play = Play.__new__(Play)
        play.wall_box_min_size = 20
        play.wall_box_merge_iou = 0.25
        play.wall_box_merge_center_distance = 35
        play.wall_history_min_hits = 2
        play.wall_history = []
        play.wall_history_use_while_moving = True
        play.wall_history_moving_frames = 2
        play.keys_hold = []
        play.last_movement = None
        play.TILE_SIZE = 60
        play.window_controller = type("DummyWindowController", (), {"scale_factor": 1.0})()
        play.wall_path_padding = 0
        play.approach_wall_padding = 0
        play.approach_side_ray_offset = 25
        play.approach_lookahead_tiles = 2.0
        play.approach_sweep_range = 120
        play.approach_sweep_step = 10
        play.roam_up_close_wall_slide_enabled = True
        play.roam_up_close_wall_distance = 130
        play.roam_up_close_wall_clearance = 42
        play.roam_up_close_wall_side_distance = 180
        return play

    def test_merges_jittered_wall_boxes(self):
        play = self.make_play()
        boxes = [
            [100, 100, 160, 160],
            [105, 102, 163, 158],
            [500, 500, 560, 560],
            [10, 10, 20, 20],
        ]

        merged = play.merge_wall_boxes(boxes)

        self.assertEqual(len(merged), 2)
        self.assertTrue(any(abs(box[0] - 102) <= 4 and abs(box[1] - 101) <= 4 for box in merged))
        self.assertTrue(any(box[0] == 500 and box[1] == 500 for box in merged))

    def test_combines_history_without_exact_coordinate_duplicates(self):
        play = self.make_play()
        play.wall_history = [
            [[100, 100, 160, 160]],
            [[103, 98, 162, 161]],
            [[700, 700, 760, 760]],
        ]

        combined = play.combine_walls_from_history()

        self.assertEqual(len(combined), 2)

    def test_current_frame_walls_are_kept_before_history_votes(self):
        play = self.make_play()
        play.wall_history = [
            [[100, 100, 160, 160]],
            [[400, 400, 460, 460]],
        ]

        combined = play.combine_walls_from_history()

        self.assertTrue(any(box[0] == 400 and box[1] == 400 for box in combined))

    def test_recent_wall_history_is_kept_while_moving(self):
        play = self.make_play()
        play.keys_hold = []
        play.last_movement = 270.0
        play.wall_history = [
            [[120, 80, 180, 140]],
            [],
        ]

        combined = play.combine_walls_from_history()

        self.assertTrue(any(box[0] == 120 and box[1] == 80 for box in combined))

    def test_upward_close_wall_slide_chooses_nearest_edge(self):
        play = self.make_play()
        player_pos = (140, 100)
        walls = [[50, 40, 150, 92]]

        slide = play.find_upward_close_wall_slide_heading(player_pos, walls)

        self.assertEqual(slide, 0.0)

    def test_upward_close_wall_slide_ignores_non_front_wall(self):
        play = self.make_play()
        player_pos = (140, 100)
        walls = [[50, 130, 150, 180]]

        slide = play.find_upward_close_wall_slide_heading(player_pos, walls)

        self.assertIsNone(slide)

    def test_attack_los_blocks_when_center_ray_hits_wall(self):
        play = self.make_play()
        play.current_brawler = "colt"
        play.brawlers_info = {"colt": {"ignore_walls_for_attacks": False, "ignore_walls_for_supers": False}}
        play.attack_wall_padding = 0
        play.attack_side_ray_offset = 30
        play.attack_min_clear_rays = 2
        play.attack_require_center_los = True

        player_pos = (100, 100)
        enemy_pos = (300, 100)
        walls = [[180, 92, 220, 108]]

        self.assertFalse(play.is_enemy_hittable(player_pos, enemy_pos, walls, "attack"))

    def test_attack_los_allows_clear_center_and_side_rays(self):
        play = self.make_play()
        play.current_brawler = "colt"
        play.brawlers_info = {"colt": {"ignore_walls_for_attacks": False, "ignore_walls_for_supers": False}}
        play.attack_wall_padding = 0
        play.attack_side_ray_offset = 20
        play.attack_min_clear_rays = 2
        play.attack_require_center_los = True

        player_pos = (100, 100)
        enemy_pos = (300, 100)
        walls = [[180, 150, 220, 190]]

        self.assertTrue(play.is_enemy_hittable(player_pos, enemy_pos, walls, "attack"))

    def test_approach_corridor_detects_wall_before_center_ray_hits(self):
        play = self.make_play()
        player_pos = (100, 100)
        walls = [[160, 120, 210, 150]]

        self.assertFalse(play.walls_block_line_of_sight(player_pos, (220, 100), walls, padding=0))
        self.assertTrue(play.is_heading_corridor_blocked(player_pos, 0.0, walls, distance=120, padding=0, side_offset=25))

    def test_refine_approach_heading_chooses_clear_corridor(self):
        play = self.make_play()
        player_pos = (100, 100)
        walls = [[160, 120, 210, 150]]

        refined = play.refine_approach_heading(player_pos, 0.0, walls, enemy_distance=300)

        self.assertNotEqual(refined, 0.0)
        self.assertFalse(play.is_heading_corridor_blocked(player_pos, refined, walls, distance=120, padding=0, side_offset=25))


if __name__ == "__main__":
    unittest.main()
