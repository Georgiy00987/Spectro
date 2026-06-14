import unittest

from control.play import Play


class TestTeammatePreference(unittest.TestCase):
    def make_play(self):
        play = Play.__new__(Play)
        play.teammate_prefer_higher = True
        play.teammate_prefer_higher_margin = 10
        play.teammate_prefer_higher_distance_penalty = 0.08
        play.teammate_hysteresis = 0.75
        play.teammate_lock_max_jump = 320
        play.teammate_lock_lost_since = 0.0
        play.locked_teammate = None
        play.locked_teammate_distance = float("inf")
        return play

    def test_prefers_higher_teammate_even_if_farther(self):
        play = self.make_play()
        player = (500, 500)
        lower_close = [485, 535, 515, 565]  # center (500, 550), close but below
        higher_far = [680, 260, 720, 300]   # center (700, 280), farther but higher

        teammate, distance = play.find_preferred_teammate([lower_close, higher_far], player)

        self.assertEqual(teammate, (700.0, 280.0))
        self.assertGreater(distance, play.get_distance((500.0, 550.0), player))

    def test_falls_back_to_closest_when_no_teammate_is_above(self):
        play = self.make_play()
        player = (500, 500)
        lower_close = [485, 535, 515, 565]
        lower_far = [680, 570, 720, 610]

        teammate, _ = play.find_preferred_teammate([lower_far, lower_close], player)

        self.assertEqual(teammate, (500.0, 550.0))

    def test_lock_switches_from_lower_to_higher_teammate(self):
        play = self.make_play()
        player = (500, 500)
        play.locked_teammate = (500.0, 550.0)
        play.locked_teammate_distance = 50.0
        lower_close = [485, 535, 515, 565]
        higher_far = [680, 260, 720, 300]

        teammate, _ = play.choose_locked_teammate(player, [lower_close, higher_far])

        self.assertEqual(teammate, (700.0, 280.0))


if __name__ == "__main__":
    unittest.main()
