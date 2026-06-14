import unittest

from control.navigation import GridNavigator, segment_blocked


class TestUpwardNavigation(unittest.TestCase):
    def test_upward_route_exists_when_straight_up_is_blocked(self):
        nav = GridNavigator(cell_size=20, grid_radius_cells=10, inflate=0)
        player = (100, 100)
        # Horizontal wall above the player blocks the direct vertical route.
        walls = [[60, 20, 140, 55]]

        cells = nav.find_upward_path_cells(player, walls, min_progress_cells=5)

        self.assertIsNotNone(cells)
        self.assertGreater(len(cells), 1)
        self.assertLess(cells[-1][1], 0)
        for i, j in cells:
            x = player[0] + i * nav.cell
            y = player[1] + j * nav.cell
            self.assertFalse(60 <= x <= 140 and 20 <= y <= 55)

    def test_upward_heading_uses_clear_first_segment(self):
        nav = GridNavigator(cell_size=20, grid_radius_cells=10, inflate=0)
        player = (100, 100)
        walls = [[60, 20, 140, 55]]

        heading = nav.next_upward_heading(player, walls, los_padding=0, min_progress_cells=5)

        self.assertIsNotNone(heading)
        # The returned heading must not point through the wall for the immediate movement probe.
        import math
        probe = (
            player[0] + math.cos(math.radians(heading)) * 40,
            player[1] + math.sin(math.radians(heading)) * 40,
        )
        self.assertFalse(segment_blocked(player, probe, walls, padding=0))

    def test_upward_heading_recovers_when_start_inside_inflated_wall(self):
        nav = GridNavigator(cell_size=20, grid_radius_cells=10, inflate=45)
        player = (100, 100)
        walls = [[50, 35, 150, 92]]

        self.assertIsNone(nav.find_upward_path_cells(player, walls, min_progress_cells=5))
        heading = nav.next_upward_heading(player, walls, los_padding=28, min_progress_cells=5)

        self.assertIsNotNone(heading)
        self.assertNotAlmostEqual(heading, 270.0, delta=5.0)


if __name__ == "__main__":
    unittest.main()
