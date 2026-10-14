"""Check package boundaries and complete source/config provenance after moves."""
import json
import subprocess
import sys
import unittest

from team4.DreamModel.config import REPO_ROOT, RenderConfig
from team4.DreamModel.runtime.provenance import code_records


class RuntimeStructureTests(unittest.TestCase):
    def test_entry_point_does_not_load_archived_implementations(self):
        code = ('import json,sys; import team4.DreamModel.main; '
                'print(json.dumps([n for n in sys.modules if n.startswith("team4.DreamModel.archive")]))')
        result = subprocess.run([sys.executable, '-c', code], cwd=REPO_ROOT,
                                text=True, capture_output=True, check=True)
        self.assertEqual(json.loads(result.stdout), [])

    def test_manifest_covers_active_helpers_and_configs(self):
        from pathlib import Path
        records = code_records()
        names = {Path(row['path']).name for row in records}
        self.assertTrue({'geometry.py', 'math_utils.py', 'media.py', 'story_rules.py',
                         'background_openended.py', 'semantic_config.json', 'assumed_layout.json'} <= names)
        self.assertTrue(all(len(row['sha256']) == 64 for row in records))
        self.assertTrue(RenderConfig().semantic_config.is_file())


if __name__ == '__main__': unittest.main()
