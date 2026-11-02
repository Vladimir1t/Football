import unittest

from fdq.matching import Candidate, match_player, match_team, name_similarity, normalize_tokens, transliterate


class NormalizationTest(unittest.TestCase):
    def test_transliteration(self):
        self.assertEqual(transliterate("Щукин Фёдор"), "shchukin fedor")

    def test_order_and_script_insensitive(self):
        self.assertEqual(normalize_tokens("Смирнов Алексей"), normalize_tokens("Aleksei Smirnov")[::1] and
                         normalize_tokens("Смирнов Алексей"))
        self.assertGreater(name_similarity("Смирнов Алексей", "Aleksei Smirnov"), 0.9)

    def test_romanization_variants(self):
        # Provider A: "Solovyov", our transliteration: "solovev"; -ий endings: "Zhukovsky" vs "zhukovskiy"
        self.assertGreater(name_similarity("Соловьёв Юрий", "Yuri Solovyov"), 0.85)
        self.assertGreater(name_similarity("Жуковский Илья", "Ilya Zhukovsky"), 0.9)

    def test_initials(self):
        self.assertGreater(name_similarity("А. Смирнов", "Aleksei Smirnov"), 0.95)
        # Same surname, wrong initial: penalized.
        self.assertLess(name_similarity("И. Смирнов", "Aleksei Smirnov"), 0.75)

    def test_different_people(self):
        self.assertLess(name_similarity("Петров Иван", "Ivan Sidorov"), 0.8)


class MatchPlayerTest(unittest.TestCase):
    def setUp(self):
        self.candidates = [
            Candidate(1, "Ivan Petrov", team_id=1, jersey=9),
            Candidate(2, "Aleksei Smirnov", team_id=1, jersey=10),
            Candidate(3, "Ivan Petrov", team_id=2, jersey=9),  # namesake in another team
        ]

    def test_team_and_jersey(self):
        res = match_player("Петров Иван", team_id=1, jersey=9, candidates=self.candidates)
        self.assertEqual((res.player_id, res.method), (1, "team+jersey"))

    def test_typo_still_matches_by_jersey(self):
        res = match_player("Петрв Иван", team_id=1, jersey=9, candidates=self.candidates)
        self.assertEqual(res.player_id, 1)

    def test_new_jersey_falls_back_to_name(self):
        res = match_player("Смирнов Алексей", team_id=1, jersey=77, candidates=self.candidates)
        self.assertEqual((res.player_id, res.method), (2, "name_fuzzy"))

    def test_jersey_reused_by_someone_else_is_not_trusted(self):
        res = match_player("Новенький Арсений", team_id=1, jersey=9, candidates=self.candidates)
        self.assertIsNone(res.player_id)

    def test_team_scopes_the_search(self):
        res = match_player("Петров Иван", team_id=2, jersey=None, candidates=self.candidates)
        self.assertEqual(res.player_id, 3)

    def test_unknown_team(self):
        self.assertIsNone(match_player("Петров Иван", team_id=None, jersey=9, candidates=self.candidates).player_id)


class MatchTeamTest(unittest.TestCase):
    TEAMS = [(1, "Сокол", ["FC Sokol"]), (2, "Звезда", ["FC Zvezda"])]

    def test_alias(self):
        self.assertEqual(match_team("FC Sokol", self.TEAMS), (1, "alias"))

    def test_transliterated_fuzzy(self):
        self.assertEqual(match_team("Zvezda", self.TEAMS), (2, "fuzzy"))

    def test_unknown(self):
        self.assertEqual(match_team("Rotor", self.TEAMS), (None, "unmatched"))


if __name__ == "__main__":
    unittest.main()
