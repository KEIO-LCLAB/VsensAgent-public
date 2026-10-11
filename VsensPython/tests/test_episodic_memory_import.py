import builtins
import importlib
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch


class TestEpisodicMemoryImportFallback(unittest.TestCase):
    def test_import_failure_falls_back_to_in_memory_store(self):
        original_module = sys.modules.pop("core.memory.episodic_memory", None)
        original_import = builtins.__import__

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "lancedb":
                raise TypeError("Plain typing.Self is not valid as type argument")
            return original_import(name, globals, locals, fromlist, level)

        try:
            with patch("builtins.__import__", side_effect=fake_import):
                module = importlib.import_module("core.memory.episodic_memory")

            self.assertIsNone(module.lancedb)
            tmpdir = tempfile.mkdtemp(prefix="episodic_memory_", dir=os.getcwd())
            try:
                memory = module.EpisodicMemory(tmpdir, openai_client=None)
                self.assertEqual(memory.count(), 0)
            finally:
                shutil.rmtree(tmpdir, ignore_errors=True)
        finally:
            sys.modules.pop("core.memory.episodic_memory", None)
            if original_module is not None:
                sys.modules["core.memory.episodic_memory"] = original_module
