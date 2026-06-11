import unittest
from pathlib import Path


class SetupBootstrapTests(unittest.TestCase):
    def test_setup_bootstrap_uses_modern_spectro_install_command(self):
        source = Path("tools/setup_bootstrap.py").read_text(encoding="utf-8")

        self.assertIn('"--spectro-install"', source)
        self.assertNotIn('["setup.py", "install"]', source)

    def test_setup_py_supports_direct_spectro_install_mode(self):
        source = Path("setup.py").read_text(encoding="utf-8")

        spectro_install_index = source.index('if "--spectro-install" in sys.argv:')
        setup_function_index = source.index("def setup_spectro():")
        setuptools_setup_index = source.index("setup(")

        self.assertGreater(spectro_install_index, setup_function_index)
        self.assertLess(spectro_install_index, setuptools_setup_index)


if __name__ == "__main__":
    unittest.main()
