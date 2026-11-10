"""Run with Python: verify animation and localisation imports without starting ZoneKit."""
import copy
import importlib.util
import json
from pathlib import Path
import re
from types import SimpleNamespace
import unittest
import tempfile
from unittest.mock import Mock, mock_open, patch


path = Path(__file__).parents[1] / 'stalker2_arsenal' / 'unreal_import.py'
spec = importlib.util.spec_from_file_location('arsenal_unreal_import', path)
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


class Properties:
    def __init__(self, **values):
        self.values = values

    def set_editor_property(self, name, value):
        self.values[name] = value

    def get_editor_property(self, name):
        return self.values[name]

    def get_name(self):
        return self.values['path'].rsplit('/', 1)[-1]

    def get_path_name(self):
        return self.values['path']

    def get_play_length(self):
        return self.values['length']


class LocalizationText(Properties):
    def __init__(self, **values):
        super().__init__(SID='', LanguagesToLocalizedStrings={})
        self.values.update(values)

    def export_text(self):
        return json.dumps(self.values, ensure_ascii=False, sort_keys=True)

    def import_text(self, text):
        quoted = r'("(?:[^"\\]|\\.)*")'
        match = re.fullmatch(r'\(SID=' + quoted + r',LanguagesToLocalizedStrings=\((.*)\)\)', text, re.S)
        if not match:
            return False
        languages = {}
        position = 0
        for translation in re.finditer(r'\(([A-Za-z]+),' + quoted + r'\)(?:,|$)', match[2]):
            if translation.start() != position or translation[1] not in (
                    'English', 'French', 'German', 'Russian', 'ChineseSimplified', 'ChineseTraditional',
                    'SpanishEuropean', 'SpanishLatinoAmerican', 'PortugalBrazilian'):
                return False
            member = re.sub(r'(?<!^)(?=[A-Z])', '_', translation[1]).upper()
            languages[f'<LocalizationLanguage.{member}: 0>'] = json.loads(translation[2])
            position = translation.end()
        if position != len(match[2]):
            return False
        self.values.update(SID=json.loads(match[1]), LanguagesToLocalizedStrings=languages)
        return True


class UIImportTests(unittest.TestCase):
    def importer(self):
        importer = runtime.Importer.__new__(runtime.Importer)
        importer.manifest = {'game_root': '/TestMod', 'replace_existing_assets': True}
        importer.plan = {'ui_images': [('image.png', '/TestMod/UI/Arsenal/Test', 'T_Test_body_inventory')]}
        importer.wanted = Mock(return_value=True)
        importer.task = Mock(return_value='task')
        importer.import_tasks = Mock(return_value=[
            '/TestMod/UI/Arsenal/Test/T_Test_body_inventory.T_Test_body_inventory'])
        texture = Properties()
        importer.library = SimpleNamespace(load_asset=Mock(return_value=texture),
                                           save_loaded_asset=Mock(return_value=True))
        return importer, texture

    def run_import(self, importer):
        enums = SimpleNamespace(
            TextureCompressionSettings=SimpleNamespace(TC_EDITOR_ICON='UI_RGBA'),
            TextureGroup=SimpleNamespace(TEXTUREGROUP_UI='UI'),
            TextureMipGenSettings=SimpleNamespace(TMGS_NO_MIPMAPS='NO_MIPS'))
        with patch.object(runtime, 'unreal', enums):
            importer.import_ui_images()

    def test_import_ui_preserves_alpha_disables_virtual_textures_and_replaces_exported_images(self):
        importer, texture = self.importer()
        self.run_import(importer)
        self.assertEqual(texture.values, {
            'srgb': True, 'compression_settings': 'UI_RGBA', 'lod_group': 'UI',
            'mip_gen_settings': 'NO_MIPS', 'virtual_texture_streaming': False})
        importer.wanted.assert_called_once_with(
            '/TestMod/UI/Arsenal/Test', 'T_Test_body_inventory', replace=True)
        importer.import_tasks.assert_called_once_with(['task'])
        importer.library.save_loaded_asset.assert_called_once_with(texture)

    def test_import_ui_reports_missing_texture_and_failed_save(self):
        importer, _texture = self.importer()
        importer.library.load_asset.return_value = None
        with self.assertRaisesRegex(RuntimeError, 'import failed'):
            self.run_import(importer)
        importer, _texture = self.importer()
        importer.library.save_loaded_asset.return_value = False
        with self.assertRaisesRegex(RuntimeError, 'Could not save'):
            self.run_import(importer)

    def test_failed_reimport_does_not_save_existing_texture_as_success(self):
        importer, _texture = self.importer()
        importer.import_tasks.return_value = []
        with self.assertRaisesRegex(RuntimeError, 'not refreshed'):
            self.run_import(importer)
        importer.library.save_loaded_asset.assert_not_called()

    def test_import_ui_never_writes_shared_game_assets(self):
        importer, _texture = self.importer()
        importer.manifest['game_root'] = '/Game'
        with self.assertRaisesRegex(RuntimeError, 'mod-owned'):
            self.run_import(importer)
        importer.import_tasks.assert_not_called()

    def test_old_manifests_have_no_ui_images(self):
        manifest = dict(textures=[], materials=[], static_meshes=[],
                        animations={'player': [], 'weapon': []}, game_root='/TestMod')
        self.assertEqual(runtime.build_plan(manifest, '.')['ui_images'], [])


class GameDataImportTests(unittest.TestCase):
    def test_old_mod_cfg_namespace_is_not_recopied_and_current_data_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            export, target = root / 'export', root / 'mod'
            for mod, value in (('OldName', 'RadiusNormalizationInterval = 0.06'),
                               ('TestMod', 'RadiusNormalizationInterval = 0.3')):
                path = export / 'GameLite' / 'ModGameData' / mod / 'WeaponData' / 'Weapon.cfg'
                path.parent.mkdir(parents=True)
                path.write_text(value, encoding='utf-8')
            patch_file = export / 'GameLite' / 'GameData' / 'Patch.cfg'
            patch_file.parent.mkdir()
            patch_file.write_text('Custom patch', encoding='utf-8')
            importer = runtime.Importer.__new__(runtime.Importer)
            importer.base_dir = str(export)
            importer.manifest = {'game_root': '/TestMod'}
            importer.mod_content_folder = Mock(return_value=str(target))
            importer.counts = {}
            with patch.object(runtime, 'warn') as warning, patch.object(runtime, 'log'):
                importer.copy_game_data()
            self.assertFalse((target / 'GameLite' / 'ModGameData' / 'OldName').exists())
            self.assertEqual((target / 'GameLite' / 'ModGameData' / 'TestMod' / 'WeaponData'
                              / 'Weapon.cfg').read_text(), 'RadiusNormalizationInterval = 0.3')
            self.assertEqual((target / 'GameLite' / 'GameData' / 'Patch.cfg').read_text(), 'Custom patch')
            self.assertEqual(importer.counts['CFG files copied'], 2)
            self.assertIn('OldName', warning.call_args.args[0])


class LocalizationArray(list):
    """Model native TArray value copying and default construction of hidden structs."""

    def copy(self):
        return LocalizationArray(LocalizationText(**copy.deepcopy(item.values)) for item in self)

    def resize(self, size):
        while len(self) < size:
            self.append(LocalizationText())


class LocalizationImportTests(unittest.TestCase):
    def make_importer(self, entries=None, texts=()):
        importer = runtime.Importer.__new__(runtime.Importer)
        importer.manifest = {'game_root': '/TestMod', 'localization': entries or [{
            'SID': 'sid_items_GunTest_name',
            'LanguagesToLocalizedStrings': {'ELocalizationLanguage::English': 'Test Weapon'},
        }]}
        asset = Properties(LocalizedTexts=LocalizationArray(texts))
        asset.modify = Mock()
        importer.text_tool_asset = Mock(return_value=asset)
        importer.library = SimpleNamespace(save_loaded_asset=Mock(return_value=True))
        importer.counts = {}
        return importer, asset

    def run_import(self, importer):
        with patch.object(runtime, 'unreal', SimpleNamespace(Object=object)), \
                patch.object(runtime, 'log'), patch.object(runtime, 'warn') as warning:
            importer.import_localization()
        return warning

    def test_localization_success_logs_all_languages_and_preserves_other_entries(self):
        entries = [{
            'SID': 'sid_items_GunTest_name',
            'LanguagesToLocalizedStrings': {
                'ELocalizationLanguage::English': 'Test Weapon',
                'ELocalizationLanguage::French': 'Arme test'},
        }]
        existing = LocalizationText(SID='unrelated', metadata='preserve me')
        importer, asset = self.make_importer(entries, [existing])
        with patch.object(runtime, 'unreal', SimpleNamespace(Object=object)), \
                patch.object(runtime, 'log') as log, patch.object(runtime, 'warn') as warning:
            importer.import_localization()
        output = '\n'.join(call.args[0] for call in log.call_args_list)
        for text in ('sid_items_GunTest_name', 'English', 'Test Weapon', 'French', 'Arme test'):
            self.assertIn(text, output)
        self.assertEqual(asset.values['LocalizedTexts'][0].export_text(), existing.export_text())
        self.assertEqual(runtime.Importer.localization_snapshot(asset.values['LocalizedTexts'])
                         ['sid_items_GunTest_name']['languages'],
                         {'English': 'Test Weapon', 'French': 'Arme test'})
        importer.library.save_loaded_asset.assert_called_once_with(asset)
        warning.assert_not_called()

    def test_localization_values_are_logged_even_when_text_tool_is_unavailable(self):
        importer = runtime.Importer.__new__(runtime.Importer)
        importer.manifest = {'localization': [{
            'SID': 'sid_items_GunTest_name',
            'LanguagesToLocalizedStrings': {'ELocalizationLanguage::English': 'Test Weapon'},
        }, {
            'SID': 'sid_items_GunTest_description',
            'LanguagesToLocalizedStrings': {'ELocalizationLanguage::English': 'Line one\nLine two'},
        }]}
        importer.text_tool_asset = Mock(side_effect=RuntimeError('not exposed'))
        with patch.object(runtime, 'log') as log, patch.object(runtime, 'warn') as warning:
            importer.import_localization()
        output = '\n'.join(call.args[0] for call in log.call_args_list)
        for text in ('sid_items_GunTest_name', 'Test Weapon', 'sid_items_GunTest_description',
                     'English', 'Line one\\nLine two'):
            self.assertIn(text, output)
        warning.assert_called_once()

    def test_empty_asset_needs_no_template_or_exposed_struct_or_enum(self):
        importer, asset = self.make_importer()
        warning = self.run_import(importer)
        self.assertEqual(asset.values['LocalizedTexts'][0].values['SID'], 'sid_items_GunTest_name')
        self.assertEqual(importer.counts['text entries'], 1)
        asset.modify.assert_called_once()
        warning.assert_not_called()

    def test_native_unlocalized_placeholder_row_is_reused(self):
        placeholder = LocalizationText(LanguagesToLocalizedStrings={
            '<LocalizationLanguage.ENGLISH: 1>': 'UNLOCALIZED MOD STRING',
        })
        unrelated = LocalizationText(SID='sid_items_Unrelated_name', LanguagesToLocalizedStrings={
            '<LocalizationLanguage.ENGLISH: 1>': 'Unrelated weapon',
        })
        importer, asset = self.make_importer(texts=[placeholder, unrelated])
        warning = self.run_import(importer)
        rows = asset.values['LocalizedTexts']
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].values['SID'], 'sid_items_GunTest_name')
        self.assertEqual(rows[1].export_text(), unrelated.export_text())
        self.assertEqual(importer.counts['text entries'], 1)
        warning.assert_not_called()

    def test_native_placeholder_does_not_hide_meaningful_unnamed_text(self):
        placeholder = LocalizationText(LanguagesToLocalizedStrings={
            '<LocalizationLanguage.ENGLISH: 1>': 'UNLOCALIZED MOD STRING',
            '<LocalizationLanguage.FRENCH: 2>': 'Keep this text',
        })
        importer, asset = self.make_importer(texts=[placeholder])
        warning = self.run_import(importer)
        warning.assert_called_once()
        asset.modify.assert_not_called()
        importer.library.save_loaded_asset.assert_not_called()
        self.assertEqual(asset.values['LocalizedTexts'][0].export_text(), placeholder.export_text())

    def test_native_placeholder_text_with_valid_sid_is_preserved(self):
        unrelated = LocalizationText(SID='sid_items_Unrelated_name', LanguagesToLocalizedStrings={
            '<LocalizationLanguage.ENGLISH: 1>': 'UNLOCALIZED MOD STRING',
        })
        importer, asset = self.make_importer(texts=[unrelated])
        warning = self.run_import(importer)
        self.assertEqual(asset.values['LocalizedTexts'][0].export_text(), unrelated.export_text())
        self.assertEqual(len(asset.values['LocalizedTexts']), 2)
        warning.assert_not_called()

    def test_upsert_preserves_unmanaged_languages_and_is_idempotent(self):
        existing = LocalizationText(SID='sid_items_GunTest_name', LanguagesToLocalizedStrings={
            '<LocalizationLanguage.ENGLISH: 0>': 'Old name',
            '<LocalizationLanguage.CHINESE_SIMPLIFIED: 1>': 'Existing translation',
            '<LocalizationLanguage.FRENCH: 2>': 'Arme test',
        }, metadata='unchanged')
        importer, asset = self.make_importer(texts=[existing])
        warning = self.run_import(importer)
        after = runtime.Importer.localization_snapshot(asset.values['LocalizedTexts'])
        self.assertEqual(after['sid_items_GunTest_name']['languages'], {
            'English': 'Test Weapon', 'ChineseSimplified': 'Existing translation', 'French': 'Arme test'})
        self.assertEqual(asset.values['LocalizedTexts'][0].values['metadata'], 'unchanged')
        self.assertEqual(existing.values['LanguagesToLocalizedStrings']['<LocalizationLanguage.ENGLISH: 0>'],
                         'Old name')
        warning.assert_not_called()
        warning = self.run_import(importer)
        warning.assert_not_called()
        importer.library.save_loaded_asset.assert_called_once()
        asset.modify.assert_called_once()

    def test_multiple_new_entries_and_special_characters_round_trip(self):
        text = 'Quoted "weapon" at C:\\mods\\test\r\nSecond line\t\u041e\u0440\u0443\u0436\u0438\u0435'
        entries = [
            {'SID': 'sid_items_Override_name',
             'LanguagesToLocalizedStrings': {'ELocalizationLanguage::English': text}},
            {'SID': 'sid_items_Override_description', 'LanguagesToLocalizedStrings': {
                'ELocalizationLanguage::ChineseSimplified': '\u6d4b\u8bd5',
                'ELocalizationLanguage::SpanishLatinoAmerican': 'Descripcion'}},
        ]
        importer, asset = self.make_importer(entries)
        warning = self.run_import(importer)
        after = runtime.Importer.localization_snapshot(asset.values['LocalizedTexts'])
        self.assertEqual(after['sid_items_Override_name']['languages'], {'English': text})
        self.assertEqual(after['sid_items_Override_description']['languages'],
                         {'ChineseSimplified': '\u6d4b\u8bd5', 'SpanishLatinoAmerican': 'Descripcion'})
        self.assertEqual(importer.counts['text entries'], 2)
        warning.assert_not_called()

    def test_invalid_sources_do_not_touch_asset(self):
        valid = {'SID': 'sid_items_GunTest_name',
                 'LanguagesToLocalizedStrings': {'ELocalizationLanguage::English': 'Weapon'}}
        for entries in (
                [valid, valid],
                [dict(valid, SID='bad"sid')],
                [dict(valid, LanguagesToLocalizedStrings={})],
                [dict(valid, LanguagesToLocalizedStrings={'English': ' '})],
                [dict(valid, LanguagesToLocalizedStrings={'English': 42})],
                [dict(valid, LanguagesToLocalizedStrings={'English': 'A',
                                                         'ELocalizationLanguage::English': 'B'})]):
            with self.subTest(entries=entries):
                importer, asset = self.make_importer(entries)
                warning = self.run_import(importer)
                warning.assert_called_once()
                importer.text_tool_asset.assert_not_called()
                importer.library.save_loaded_asset.assert_not_called()
                asset.modify.assert_not_called()

    def test_duplicate_existing_sids_are_not_overwritten(self):
        existing = LocalizationText(SID='duplicate')
        importer, asset = self.make_importer(texts=[existing, existing])
        warning = self.run_import(importer)
        self.assertIn('duplicate', warning.call_args.args[0])
        asset.modify.assert_not_called()
        importer.library.save_loaded_asset.assert_not_called()

    def test_empty_text_tool_rows_are_reused_and_real_entry_indices_are_preserved(self):
        existing = LocalizationText(SID='sid_items_GunTest_name',
                                    LanguagesToLocalizedStrings={'English': 'Old name'})
        unrelated = LocalizationText(SID='other', LanguagesToLocalizedStrings={'French': 'Keep me'})
        entries = [
            {'SID': 'sid_items_GunTest_name', 'LanguagesToLocalizedStrings': {'English': 'New name'}},
            {'SID': 'sid_items_GunTest_description', 'LanguagesToLocalizedStrings': {'English': 'Description'}},
            {'SID': 'sid_items_GunTest_MagExtended_name', 'LanguagesToLocalizedStrings': {'English': 'Magazine'}},
        ]
        importer, asset = self.make_importer(entries, [
            LocalizationText(), existing, LocalizationText(LanguagesToLocalizedStrings={'English': ''}), unrelated])
        original = [entry.export_text() for entry in asset.values['LocalizedTexts']]
        warning = self.run_import(importer)
        warning.assert_not_called()
        after = asset.values['LocalizedTexts']
        self.assertEqual(len(after), 4)
        self.assertEqual(after[1].values['SID'], 'sid_items_GunTest_name')
        self.assertEqual(after[0].values['SID'], 'sid_items_GunTest_description')
        self.assertEqual(after[2].values['SID'], 'sid_items_GunTest_MagExtended_name')
        self.assertEqual(after[3].export_text(), original[3])
        self.assertEqual(importer.counts['text entries'], 3)
        self.run_import(importer).assert_not_called()
        importer.library.save_loaded_asset.assert_called_once()

    def test_empty_sid_with_meaningful_translation_is_not_discarded(self):
        importer, asset = self.make_importer(texts=[
            LocalizationText(LanguagesToLocalizedStrings={'English': 'Unassigned text'})])
        warning = self.run_import(importer)
        self.assertIn("empty or duplicate", warning.call_args.args[0])
        asset.modify.assert_not_called()
        importer.library.save_loaded_asset.assert_not_called()

    def test_empty_placeholder_rows_are_restored_when_save_fails(self):
        importer, asset = self.make_importer(texts=[LocalizationText()])
        original = asset.values['LocalizedTexts']
        importer.library.save_loaded_asset.return_value = False
        warning = self.run_import(importer)
        self.assertIn('could not save', warning.call_args.args[0])
        self.assertIs(asset.values['LocalizedTexts'], original)
        self.assertEqual(original[0].values['SID'], '')

    def test_struct_updates_are_written_back_when_array_getter_returns_a_value_copy(self):
        class ValueCopyArray(LocalizationArray):
            def copy(self):
                return ValueCopyArray(super().copy())

            def __getitem__(self, index):
                value = super().__getitem__(index)
                return LocalizationText(**copy.deepcopy(value.values))

        importer, asset = self.make_importer()
        asset.values['LocalizedTexts'] = ValueCopyArray([LocalizationText()])
        warning = self.run_import(importer)
        warning.assert_not_called()
        self.assertEqual(asset.values['LocalizedTexts'][0].values['SID'], 'sid_items_GunTest_name')
        importer.library.save_loaded_asset.assert_called_once()

    def test_rejected_struct_text_leaves_original_unchanged(self):
        importer, asset = self.make_importer()
        original = asset.values['LocalizedTexts']
        with patch.object(LocalizationText, 'import_text', return_value=False):
            warning = self.run_import(importer)
        self.assertIn('rejected', warning.call_args.args[0])
        self.assertIs(asset.values['LocalizedTexts'], original)
        asset.modify.assert_not_called()
        importer.library.save_loaded_asset.assert_not_called()

    def test_save_failure_restores_original_and_reports_warning(self):
        importer, asset = self.make_importer()
        original = asset.values['LocalizedTexts']
        importer.library.save_loaded_asset.return_value = False
        warning = self.run_import(importer)
        self.assertIn('could not save', warning.call_args.args[0])
        self.assertIs(asset.values['LocalizedTexts'], original)
        self.assertNotIn('text entries', importer.counts)

    def test_readback_mismatch_is_not_saved(self):
        importer, asset = self.make_importer()
        original = asset.values['LocalizedTexts']

        def drop_entries(name, value):
            asset.values[name] = original if value is original else LocalizationArray()

        asset.set_editor_property = drop_entries
        warning = self.run_import(importer)
        self.assertIn('SID set differs', warning.call_args.args[0])
        self.assertIs(asset.values['LocalizedTexts'], original)
        importer.library.save_loaded_asset.assert_not_called()

    def test_silent_struct_translation_failure_is_detected_before_assignment(self):
        importer, asset = self.make_importer()
        original = asset.values['LocalizedTexts']
        native_import = LocalizationText.import_text

        def incorrect_translation(item, text):
            native_import(item, text)
            item.values['LanguagesToLocalizedStrings'] = {'English': 'Wrong text'}
            return True

        with patch.object(LocalizationText, 'import_text', incorrect_translation):
            warning = self.run_import(importer)
        self.assertIn('translations differ', warning.call_args.args[0])
        self.assertIs(asset.values['LocalizedTexts'], original)
        asset.modify.assert_not_called()
        importer.library.save_loaded_asset.assert_not_called()

    def test_unrelated_entry_change_is_detected(self):
        item = LocalizationText(SID='unrelated', metadata='original')
        before = runtime.Importer.localization_snapshot([item])
        item.values['metadata'] = 'corrupted'
        with self.assertRaisesRegex(RuntimeError, 'unrelated'):
            runtime.Importer.validate_localization([item], before, {})

    def test_save_exception_restores_original(self):
        importer, asset = self.make_importer()
        original = asset.values['LocalizedTexts']
        importer.library.save_loaded_asset.side_effect = RuntimeError('Read only')
        warning = self.run_import(importer)
        self.assertIn('Read only', warning.call_args.args[0])
        self.assertIs(asset.values['LocalizedTexts'], original)
        self.assertNotIn('text entries', importer.counts)

    def test_no_localization_does_not_touch_asset(self):
        importer, asset = self.make_importer()
        importer.manifest['localization'] = []
        warning = self.run_import(importer)
        warning.assert_not_called()
        importer.text_tool_asset.assert_not_called()
        asset.modify.assert_not_called()

    def test_dry_run_reports_sids_without_constructing_importer(self):
        importer, _ = self.make_importer()
        manifest = dict(importer.manifest, textures=[], materials=[], static_meshes=[],
                        animations={'player': [], 'weapon': []})
        with patch.object(runtime, 'unreal', SimpleNamespace()), \
                patch.object(runtime, 'find_manifest', return_value=r'C:\export\import_test.json'), \
                patch('builtins.open', mock_open(read_data=json.dumps(manifest))), \
                patch('builtins.print') as output, patch.object(runtime, 'Importer') as constructor:
            runtime._main(['--dry-run'])
        constructor.assert_not_called()
        output.assert_any_call('localization: 1')
        output.assert_any_call('   ', 'sid_items_GunTest_name')

    def test_language_names_from_manifest_and_native_enums(self):
        for key, expected in (
                ('ELocalizationLanguage::English', 'English'),
                ('<LocalizationLanguage.CHINESE_SIMPLIFIED: 13>', 'ChineseSimplified'),
                ('LocalizationLanguage.PORTUGAL_BRAZILIAN', 'PortugalBrazilian'),
                ('ChineseTraditional', 'ChineseTraditional')):
            with self.subTest(key=key):
                self.assertEqual(runtime.Importer.localization_language(key), expected)

    def registry_unreal(self, names):
        assets = [SimpleNamespace(
            asset_name=name, package_name=f'/TestMod/Localization/{name}',
            asset_class_path=SimpleNamespace(asset_name='LocalizationModTextToolAsset'),
            get_asset=Mock(return_value=object())) for name in names]
        registry = SimpleNamespace(get_assets_by_path=Mock(return_value=assets))
        tools = SimpleNamespace(create_asset=Mock(return_value=object()))
        unreal = SimpleNamespace(
            AssetRegistryHelpers=SimpleNamespace(get_asset_registry=lambda: registry),
            AssetToolsHelpers=SimpleNamespace(get_asset_tools=lambda: tools),
            LocalizationModTextToolAsset=object())
        return unreal, registry, tools, assets

    def test_selects_existing_nonstandard_asset_or_preferred_name(self):
        for names, index in ((['L_TestMod'], 0), (['Other', 'TestModTextToolAsset'], 1)):
            importer, _ = self.make_importer()
            unreal, registry, tools, assets = self.registry_unreal(names)
            with patch.object(runtime, 'unreal', unreal):
                self.assertIs(runtime.Importer.text_tool_asset(importer), assets[index].get_asset())
            registry.get_assets_by_path.assert_called_once_with('/TestMod', recursive=True)
            tools.create_asset.assert_not_called()

    def test_ambiguous_assets_require_explicit_resolution(self):
        importer, _ = self.make_importer()
        unreal, _, tools, _ = self.registry_unreal(['First', 'Second'])
        with patch.object(runtime, 'unreal', unreal), self.assertRaisesRegex(RuntimeError, 'multiple'):
            runtime.Importer.text_tool_asset(importer)
        tools.create_asset.assert_not_called()

    def test_creates_mod_asset_when_none_exists(self):
        importer, _ = self.make_importer()
        unreal, _, tools, _ = self.registry_unreal([])
        with patch.object(runtime, 'unreal', unreal):
            self.assertIs(runtime.Importer.text_tool_asset(importer), tools.create_asset.return_value)
        tools.create_asset.assert_called_once_with(
            'TestModTextToolAsset', '/TestMod', unreal.LocalizationModTextToolAsset, None)

    def test_shared_content_mounts_are_rejected(self):
        for mount in ('/Game', '/Engine', '/Game/Subfolder', '/'):
            importer, _ = self.make_importer()
            importer.manifest['game_root'] = mount
            with patch.object(runtime, 'unreal', SimpleNamespace()), self.assertRaisesRegex(
                    RuntimeError, 'mod-owned'):
                runtime.Importer.text_tool_asset(importer)


class AnimationImportTests(unittest.TestCase):
    def make_importer(self):
        importer = runtime.Importer.__new__(runtime.Importer)
        importer.wanted = Mock(return_value=True)
        importer.skeleton = Mock(return_value=object())
        importer.counts = {}
        importer.library = SimpleNamespace(
            does_asset_exist=Mock(return_value=False), load_asset=Mock(),
            save_loaded_asset=Mock(return_value=True))
        imported = []

        def import_tasks(tasks):
            imported.extend(tasks)
            for task in tasks:
                task.set_editor_property(
                    'imported_object_paths', [task.get_editor_property('destination_name')])

        importer.tools = SimpleNamespace(import_asset_tasks=import_tasks)
        unreal = SimpleNamespace(
            log=Mock(),
            log_warning=Mock(),
            FbxImportUI=lambda: Properties(anim_sequence_import_data=Properties()),
            AssetImportTask=Properties,
            FbxFactory=Properties,
            FBXImportType=SimpleNamespace(FBXIT_ANIMATION='animation'),
            AnimPoseEvaluationOptions=SimpleNamespace,
            AnimDataEvalType=SimpleNamespace(RAW='raw'),
            AnimPoseSpaces=SimpleNamespace(LOCAL='local'),
            AdditiveAnimationType=SimpleNamespace(AAT_NONE='none', AAT_LOCAL_SPACE_BASE='local'),
            SystemLibrary=SimpleNamespace(
                get_console_variable_bool_value=Mock(return_value=True),
                execute_console_command=Mock()),
        )
        return importer, unreal, imported

    def test_reimport_preserves_custom_additive_settings(self):
        importer, unreal, _ = self.make_importer()
        reference = object()
        values = dict(path='/Test/reload', additive_anim_type='mesh', ref_pose_type='frame',
                      ref_frame_index=3, ref_pose_seq=reference)
        asset = Properties(**values)
        importer.library.does_asset_exist.return_value = True
        importer.library.load_asset.return_value = asset
        native_import = importer.tools.import_asset_tasks

        def reset_settings(tasks):
            native_import(tasks)
            asset.values.update(additive_anim_type='none', ref_pose_type='skeleton',
                                ref_frame_index=0, ref_pose_seq=None)

        importer.tools.import_asset_tasks = reset_settings
        with patch.object(runtime, 'unreal', unreal):
            importer.import_animations([(r'C:\export\reload.fbx', '/Test', 'reload')], '/Game/Skeleton')
        self.assertEqual(asset.values, values)
        importer.library.save_loaded_asset.assert_called_once_with(asset)

    def test_exported_overlay_recovers_lost_template_additive_settings(self):
        importer, unreal, _ = self.make_importer()
        unreal.AdditiveAnimationType = SimpleNamespace(AAT_NONE='none', AAT_LOCAL_SPACE_BASE='local')
        package = '/Mod/Animations/Player/gun/Reload/AS_fp_gun_reload'
        original_package = '/Game/Animations/Player/udp/Reload/AS_fp_udp_reload'
        base = Properties(path='/Mod/Animations/Player/gun/Idle/AS_fp_gun_idle', additive_anim_type='none')
        original_base = Properties(path='/Game/Animations/Player/udp/Idle/AS_fp_udp_idle')
        asset = Properties(path=package, additive_anim_type='none', ref_pose_type='skeleton',
                           ref_frame_index=0, ref_pose_seq=None, tracks='edited')
        original = Properties(path=original_package, additive_anim_type='local',
                              ref_pose_type='frame', ref_frame_index=2, ref_pose_seq=original_base)
        packages = {package: asset, original_package: original, base.get_path_name(): base}
        importer.manifest = {'weapon': 'gun', 'template_weapon': 'udp', 'game_root': '/Mod'}
        importer.plan = {'player_animations': [('reload.fbx', *package.rsplit('/', 1))]}
        importer.mod_assets = lambda: {'sequence': {p.lower(): p for p in (package, base.get_path_name())}}
        importer.library = SimpleNamespace(
            does_asset_exist=lambda path: path in packages,
            load_asset=lambda path: packages[path], save_loaded_asset=Mock(return_value=True))
        with patch.object(runtime, 'unreal', unreal):
            importer.update_additive_playback()
            importer.update_additive_playback()
        self.assertEqual(asset.get_editor_property('additive_anim_type'), 'local')
        self.assertEqual(asset.get_editor_property('ref_pose_type'), 'frame')
        self.assertEqual(asset.get_editor_property('ref_frame_index'), 2)
        self.assertIs(asset.get_editor_property('ref_pose_seq'), base)
        self.assertEqual(asset.get_editor_property('tracks'), 'edited')
        importer.library.save_loaded_asset.assert_called_once_with(asset)

    def test_additive_restore_reports_save_failure(self):
        importer, unreal, _ = self.make_importer()
        asset = Properties(path='/Test/reload', additive_anim_type='none')
        importer.library.save_loaded_asset.return_value = False
        with patch.object(runtime, 'unreal', unreal):
            with self.assertRaisesRegex(RuntimeError, 'Could not save additive settings'):
                importer.restore_additive_settings(asset, {'additive_anim_type': 'local'})

    def test_unchanged_additive_settings_are_not_saved(self):
        importer, unreal, _ = self.make_importer()
        asset = Properties(path='/Test/idle', additive_anim_type='none')
        with patch.object(runtime, 'unreal', unreal):
            importer.restore_additive_settings(asset, {'additive_anim_type': 'none'})
        importer.library.save_loaded_asset.assert_not_called()

    def test_animation_tasks_preserve_baked_local_transforms(self):
        importer, unreal, imported = self.make_importer()
        files = [
            (r'C:\export\reload.fbx', '/Test/Animations', 'reload'),
            (r'C:\export\idle.fbx', '/Test/Animations', 'idle'),
        ]
        with patch.object(runtime, 'unreal', unreal):
            importer.import_animations(files, '/Game/TestSkeleton')
        self.assertEqual(len(imported), 2)
        self.assertEqual(importer.counts, {'imported': 2})
        factories = []
        for task, (filename, folder, name) in zip(imported, files):
            self.assertEqual(task.get_editor_property('filename'), filename)
            self.assertEqual(task.get_editor_property('destination_path'), folder)
            self.assertEqual(task.get_editor_property('destination_name'), name)
            self.assertTrue(task.get_editor_property('replace_existing_settings'))
            options = task.get_editor_property('options')
            self.assertEqual(options.get_editor_property('mesh_type_to_import'), 'animation')
            self.assertIs(options.get_editor_property('skeleton'), importer.skeleton.return_value)
            self.assertTrue(options.get_editor_property('anim_sequence_import_data').get_editor_property(
                'preserve_local_transform'))
            self.assertFalse(options.get_editor_property('anim_sequence_import_data').get_editor_property(
                'use_default_sample_rate'))
            self.assertEqual(options.get_editor_property('anim_sequence_import_data').get_editor_property(
                'custom_sample_rate'), 0)
            factories.append(task.get_editor_property('factory'))
            self.assertIsInstance(factories[-1], Properties)
        self.assertIsNot(factories[0], factories[1])
        self.assertEqual(unreal.SystemLibrary.execute_console_command.call_args_list, [
            ((None, 'Interchange.FeatureFlags.Import.FBX 0'),),
            ((None, 'Interchange.FeatureFlags.Import.FBX 1'),),
        ])

    def test_interchange_setting_restored_after_import_failure(self):
        importer, unreal, _imported = self.make_importer()
        importer.tools.import_asset_tasks = Mock(side_effect=RuntimeError('import failed'))
        with patch.object(runtime, 'unreal', unreal):
            with self.assertRaisesRegex(RuntimeError, 'import failed'):
                importer.import_animations([(r'C:\export\reload.fbx', '/Test', 'reload')], '/Game/Skeleton')
        self.assertEqual(unreal.SystemLibrary.execute_console_command.call_count, 2)
        self.assertEqual(unreal.SystemLibrary.execute_console_command.call_args.args,
                         (None, 'Interchange.FeatureFlags.Import.FBX 1'))

    def test_disabled_interchange_setting_is_left_alone(self):
        importer, unreal, _imported = self.make_importer()
        unreal.SystemLibrary.get_console_variable_bool_value.return_value = False
        with patch.object(runtime, 'unreal', unreal):
            importer.import_animations([(r'C:\export\reload.fbx', '/Test', 'reload')], '/Game/Skeleton')
        unreal.SystemLibrary.execute_console_command.assert_not_called()

    def test_skipped_animations_do_not_create_import_tasks(self):
        importer, unreal, imported = self.make_importer()
        importer.wanted.return_value = False
        with patch.object(runtime, 'unreal', unreal):
            importer.import_animations([(r'C:\export\reload.fbx', '/Test', 'reload')], '/Game/TestSkeleton')
        self.assertEqual(imported, [])
        importer.skeleton.assert_not_called()

    def test_static_import_rejects_planned_vanilla_package_collision(self):
        importer, unreal, imported = self.make_importer()
        importer.manifest = {'game_root': '/Test'}
        importer.plan = {'static_meshes': [(r'C:\export\mesh.fbx', '/Test/Weapons', 'VanillaMesh')]}
        importer.library = SimpleNamespace(does_asset_exist=lambda path: path == '/Game/Weapons/VanillaMesh')
        unreal.AssetRegistryHelpers = SimpleNamespace(get_asset_registry=lambda: SimpleNamespace(
            get_assets_by_path=lambda *args, **kwargs: []))
        with patch.object(runtime, 'unreal', unreal):
            with self.assertRaisesRegex(RuntimeError, 'override vanilla weapons'):
                importer.import_static_meshes()
        self.assertEqual(imported, [])

    def test_static_import_rejects_stale_mod_override_not_in_manifest(self):
        importer, unreal, imported = self.make_importer()
        importer.manifest = {'game_root': '/Test'}
        importer.plan = {'static_meshes': []}
        importer.library = SimpleNamespace(does_asset_exist=lambda path: path == '/Game/Weapons/OldMesh')
        old = SimpleNamespace(package_name='/Test/Weapons/OldMesh',
                              asset_class_path=SimpleNamespace(asset_name='StaticMesh'))
        unreal.AssetRegistryHelpers = SimpleNamespace(get_asset_registry=lambda: SimpleNamespace(
            get_assets_by_path=lambda *args, **kwargs: [old]))
        with patch.object(runtime, 'unreal', unreal):
            with self.assertRaisesRegex(RuntimeError, 'OldMesh'):
                importer.import_static_meshes()
        self.assertEqual(imported, [])

    def test_template_package_swaps_only_complete_weapon_tokens(self):
        self.assertEqual(runtime.template_sequence_package(
            '/Mod/ladybuggun/AS_fp_ladybuggun_shoot', 'ladybuggun', 'udp', '/Mod'),
            '/Game/udp/AS_fp_udp_shoot')
        self.assertEqual(runtime.template_sequence_package(
            '/Mod/ladybuggun_extra/ladybuggunner', 'ladybuggun', 'udp', '/Mod'),
            '/Game/udp_extra/ladybuggunner')
        with self.assertRaises(ValueError):
            runtime.template_sequence_package('/Game/udp/idle', 'ladybuggun', 'udp', '/Mod')

    def test_raw_comparison_checks_every_track_key(self):
        importer, unreal, _ = self.make_importer()
        a = Properties(path='/Mod/shoot', length=1)
        b = Properties(path='/Game/shoot', length=1)
        keys = [SimpleNamespace(x=0, y=0, z=0), SimpleNamespace(x=1, y=0, z=0)]
        tracks = {a: {'hand': (keys, keys, keys)}, b: {'hand': (list(keys), keys, keys)}}
        unreal.AnimationLibrary = SimpleNamespace(
            get_animation_track_names=lambda asset: list(tracks[asset]),
            get_num_frames=lambda _asset: 1,
            get_animation_interpolation_type=lambda _asset: 'linear')
        unreal.AnimPoseExtensions = SimpleNamespace(
            get_anim_pose_at_time=lambda asset, time, _options: (asset, round(time)),
            get_bone_pose=lambda pose, name, _space: SimpleNamespace(
                translation=tracks[pose[0]][name][0][pose[1]],
                rotation=SimpleNamespace(x=0, y=0, z=0, w=1),
                scale3d=SimpleNamespace(x=1, y=1, z=1)))
        with patch.object(runtime, 'unreal', unreal):
            self.assertTrue(importer.same_raw_animation(a, b))
            unreal.AnimationLibrary.get_animation_interpolation_type = lambda asset: 'step' if asset is b else 'linear'
            self.assertFalse(importer.same_raw_animation(a, b))
            unreal.AnimationLibrary.get_animation_interpolation_type = lambda _asset: 'linear'
            tracks[b]['hand'] = ([keys[0], SimpleNamespace(x=1.01, y=0, z=0)], keys, keys)
            self.assertFalse(importer.same_raw_animation(a, b))
            tracks[b] = {}
            self.assertFalse(importer.same_raw_animation(a, b))

    def test_quaternion_sign_does_not_trigger_an_idle_rewrite(self):
        def transform(rotation, x=0):
            return SimpleNamespace(
                translation=SimpleNamespace(x=x, y=0, z=0),
                rotation=rotation, scale3d=SimpleNamespace(x=1, y=1, z=1))

        a = transform(SimpleNamespace(x=.1, y=.2, z=.3, w=.9))
        b = transform(SimpleNamespace(x=-.1, y=-.2, z=-.3, w=-.9), x=4.8e-5)
        self.assertTrue(runtime.transforms_equal(a, b))
        b.translation.x = 1.1e-4
        self.assertFalse(runtime.transforms_equal(a, b))
        b.translation.x = 0
        b.scale3d.x += 2e-5
        self.assertFalse(runtime.transforms_equal(a, b))
        b.scale3d.x = 1
        b.rotation.z = -.4
        self.assertFalse(runtime.transforms_equal(a, b))

    def test_additive_idle_uses_exported_pose_without_changing_timing_or_base(self):
        importer, unreal, _ = self.make_importer()
        source = Properties(path='/Mod/Idle/idle', length=2, additive_anim_type='none')
        target = Properties(path='/Mod/Additive/idle_add', length=1,
                            additive_anim_type='local', ref_pose_seq='common', curves='retained')
        tracks = {source: {'hand': ([], [], [])}, target: {'stale': ([], [], [])}}
        controller = Mock()
        controller.remove_all_bone_tracks.side_effect = lambda _transact: tracks[target].clear()
        controller.add_bone_curve.return_value = True

        def set_keys(name, positions, rotations, scales, should_transact):
            tracks[target][name] = (positions, rotations, scales)
            return True

        controller.set_bone_track_keys.side_effect = set_keys
        target.controller = controller
        importer.library = SimpleNamespace(save_loaded_asset=Mock())
        importer.count = Mock()
        unreal.AnimationLibrary = SimpleNamespace(
            get_num_frames=lambda _asset: 2,
            get_animation_track_names=lambda asset: list(tracks[asset]),
            get_raw_track_data=lambda asset, name: tracks[asset][name])
        unreal.AdditiveAnimationType = SimpleNamespace(
            AAT_NONE='none', AAT_LOCAL_SPACE_BASE='local', AAT_ROTATION_OFFSET_MESH_SPACE='mesh')
        unreal.AnimDataEvalType = SimpleNamespace(RAW='raw')
        unreal.AnimPoseSpaces = SimpleNamespace(LOCAL='local')
        unreal.AnimPoseEvaluationOptions = SimpleNamespace
        unreal.AnimPoseExtensions = SimpleNamespace(
            get_anim_pose_at_time=lambda asset, time, _options: (asset, time),
            get_bone_pose=lambda pose, name, _space: SimpleNamespace(
                translation=(SimpleNamespace(x=pose[1], y=0, z=0) if pose[0] is source
                             else tracks[target][name][0][round(pose[1] * 2)]),
                rotation=SimpleNamespace(x=0, y=0, z=0, w=1),
                scale3d=SimpleNamespace(x=1, y=1, z=1)))
        with patch.object(runtime, 'unreal', unreal):
            importer.sync_additive_idle(source, target)
            self.assertEqual([v.x for v in tracks[target]['hand'][0]], [0, 1, 2])
            self.assertNotIn('stale', tracks[target])
            self.assertEqual(target.get_play_length(), 1)
            self.assertEqual(target.get_editor_property('ref_pose_seq'), 'common')
            self.assertEqual(target.get_editor_property('curves'), 'retained')
            self.assertEqual(target.get_editor_property('additive_anim_type'), 'local')
            importer.sync_additive_idle(source, target)
        controller.open_bracket.assert_called_once()
        importer.library.save_loaded_asset.assert_called_once_with(target)

    def test_exported_aim_transitions_keep_their_additive_mode_and_reference(self):
        importer, unreal, _ = self.make_importer()
        unreal.AdditiveAnimationType = SimpleNamespace(
            AAT_NONE='none', AAT_LOCAL_SPACE_BASE='local', AAT_ROTATION_OFFSET_MESH_SPACE='mesh')
        package = '/Mod/Animations/Player/gun/Idle/AS_fp_gun_idle_to_aim'
        asset = Properties(path=package, additive_anim_type='local', tracks='edited',
                           ref_pose_seq='common', ref_pose_type='frame', ref_frame_index=0)
        importer.plan = {'player_animations': [('aim.fbx', *package.rsplit('/', 1))]}
        importer.manifest = {'weapon': 'gun', 'template_weapon': 'udp', 'game_root': '/Mod'}
        importer.mod_assets = lambda: {'sequence': {package.lower(): package}}
        importer.library = SimpleNamespace(load_asset=lambda _path: asset, save_loaded_asset=Mock(return_value=True))
        with patch.object(runtime, 'unreal', unreal):
            importer.update_additive_playback()
            importer.update_additive_playback()
            self.assertEqual(asset.get_editor_property('additive_anim_type'), 'local')
            asset.set_editor_property('additive_anim_type', 'mesh')
            importer.update_additive_playback()
            self.assertEqual(asset.get_editor_property('additive_anim_type'), 'mesh')
        self.assertEqual(asset.get_editor_property('tracks'), 'edited')
        self.assertEqual(asset.get_editor_property('ref_pose_seq'), 'common')
        self.assertEqual(asset.get_editor_property('ref_pose_type'), 'frame')
        self.assertEqual(asset.get_editor_property('ref_frame_index'), 0)
        importer.library.save_loaded_asset.assert_not_called()
        self.assertEqual(importer.counts, {})

    def test_overlay_reference_restored_only_when_raw_tracks_unchanged(self):
        importer, unreal, _ = self.make_importer()
        base = Properties(path='/Mod/udp_idle')
        original_base = Properties(path='/Game/udp_idle')
        overlay = Properties(path='/Mod/Animations/Player/gun/AS_fp_gun_shoot',
                             additive_anim_type='local', ref_pose_seq=base, ref_pose_type='frame', ref_frame_index=0)
        original = Properties(path='/Game/Animations/Player/udp/AS_fp_udp_shoot',
                              additive_anim_type='local', ref_pose_seq=original_base, ref_pose_type='frame', ref_frame_index=0)
        packages = {overlay.get_path_name(): overlay, original.get_path_name(): original}
        importer.library = SimpleNamespace(
            load_asset=packages.__getitem__, does_asset_exist=packages.__contains__,
            save_loaded_asset=Mock())
        importer.manifest = {'weapon': 'gun', 'template_weapon': 'udp', 'game_root': '/Mod'}
        importer.plan = {'player_animations': []}
        importer.mod_assets = lambda: {'sequence': {overlay.get_path_name().lower(): overlay.get_path_name()}}
        importer.same_raw_animation = Mock(return_value=False)
        importer.count = Mock()
        unreal.AdditiveAnimationType = SimpleNamespace(AAT_NONE='none')
        with patch.object(runtime, 'unreal', unreal):
            importer.update_additive_playback()
            self.assertIs(overlay.get_editor_property('ref_pose_seq'), base)
            importer.same_raw_animation.return_value = True
            overlay.set_editor_property('ref_frame_index', 1)
            importer.update_additive_playback()
            self.assertIs(overlay.get_editor_property('ref_pose_seq'), base)
            overlay.set_editor_property('ref_frame_index', 0)
            importer.update_additive_playback()
            self.assertIs(overlay.get_editor_property('ref_pose_seq'), original_base)
            importer.update_additive_playback()
        importer.library.save_loaded_asset.assert_called_once_with(overlay)

    def test_explicitly_exported_additive_idle_is_not_regenerated(self):
        importer, unreal, _ = self.make_importer()
        idle = '/Mod/Animations/Player/gun/Idle/AS_fp_gun_idle'
        companion = '/Mod/Animations/Player/gun/Additive/AS_fp_gun_idle_add'
        importer.manifest = {'weapon': 'gun', 'template_weapon': 'udp', 'game_root': '/Mod'}
        importer.plan = {'player_animations': [
            ('idle.fbx', *idle.rsplit('/', 1)), ('idle_add.fbx', *companion.rsplit('/', 1))]}
        importer.mod_assets = lambda: {'sequence': {p.lower(): p for p in (idle, companion)}}
        importer.sync_additive_idle = Mock()
        importer.library = SimpleNamespace(
            load_asset=lambda path: Properties(additive_anim_type='none' if path == idle else 'local'),
            does_asset_exist=Mock(return_value=False), save_loaded_asset=Mock())
        with patch.object(runtime, 'unreal', unreal):
            importer.update_additive_playback()
        importer.sync_additive_idle.assert_not_called()
        importer.library.save_loaded_asset.assert_not_called()


class Name(str):
    """Stands in for unreal.Name map keys."""


class Struct:
    """An Unreal struct wrapper: property reads return copies, like the editor's Python."""
    def __init__(self, **values):
        self.values = values

    def get_editor_property(self, name):
        return copy.deepcopy(self.values[name])

    def set_editor_property(self, name, value):
        self.values[name] = copy.deepcopy(value)

    def export_text(self):
        def render(value):
            if isinstance(value, Struct):
                return value.export_text()
            if isinstance(value, dict):
                return '{' + ','.join(f'{key}:{render(item)}' for key, item in sorted(value.items())) + '}'
            return repr(value)
        return render(self.values)


class Collection(Struct):
    def get_name(self):
        return 'AnimCollection_fp_gun'


def reload_entry(montage):
    return Struct(magazine_reload_animations={'full': montage}, magazine_reload_states={})


def attach_entry(attach, detach=None):
    return Struct(attach_animation=Struct(character=attach, weapon=attach + '_w'),
                  detach_animation=Struct(character=detach, weapon=detach))


class CollectionSidTests(unittest.TestCase):
    MAGAZINES = [{'sid': 'GunGun_MagDefault', 'name': 'Default', 'preinstalled': True},
                 {'sid': 'GunGun_MagExtended', 'name': 'Extended', 'preinstalled': False}]

    def make(self, reloading=None, attaching=None, attachments=({'sid': 'EN_Silen_2', 'kind': 'silencer'},)):
        reloading = reloading or {Name('GunGun_MagDefault'): reload_entry('MG_reload'),
                                  Name('GunGun_MagExtended'): reload_entry('MG_reload_increased')}
        one_hand = {Name('GunUDP_MagDefault'): reload_entry('MG_reload_one_hand'),
                    Name('GunUDP_MagIncreased'): reload_entry('MG_reload_increased_one_hand')}
        attaching = attaching or {'GunGun_MagDefault': attach_entry('MG_mag_attach', 'MG_mag_detach'),
                                  'EN_Silen_1': attach_entry('MG_silencer_attach')}
        collection = Collection(internal_animations=Struct(
            reloading=reloading, one_hand_reloading=one_hand, attaching_by_sid=attaching,
            shooting={'loose': 'MG_shoot'}))
        importer = runtime.Importer.__new__(runtime.Importer)
        importer.manifest = {'magazines': self.MAGAZINES, 'attachments': list(attachments)}
        importer.library = SimpleNamespace(save_loaded_asset=Mock(return_value=True))
        return importer, collection

    @staticmethod
    def maps(collection):
        internal = collection.get_editor_property('internal_animations')
        return {field: internal.get_editor_property(field) for field in runtime.COLLECTION_SID_MAPS}

    def test_plan_maps_template_magazines_and_attachment_kinds(self):
        plan = runtime.planned_collection_sids(
            ['GunUDP_MagDefault', 'GunUDP_MagIncreased', 'EN_Silen_1'], self.MAGAZINES,
            [{'sid': 'EN_Silen_2', 'kind': 'silencer'}, {'sid': 'EN_Laser_1', 'kind': 'laser'}])
        self.assertEqual(plan, {'GunUDP_MagDefault': 'GunGun_MagDefault',
                                'GunUDP_MagIncreased': 'GunGun_MagExtended',
                                'EN_Silen_1': 'EN_Silen_2'})

    def test_plan_removes_donor_even_when_target_already_present(self):
        self.assertEqual(runtime.planned_collection_sids(
            ['GunGun_MagDefault', 'GunUDP_MagDefault', 'EN_Silen_2'], self.MAGAZINES,
            [{'sid': 'EN_Silen_2', 'kind': 'silencer'}]),
            {'GunUDP_MagDefault': 'GunGun_MagDefault'})

    def test_attachment_key_is_not_used_as_a_magazine_template(self):
        self.assertEqual(runtime.planned_collection_sids(
            ['EN_Silen_1'], self.MAGAZINES, [{'sid': 'EN_Silen_2', 'kind': 'silencer'}]),
            {'EN_Silen_1': 'EN_Silen_2'})

    def test_missing_one_hand_and_silencer_entries_are_copied_from_template(self):
        importer, collection = self.make()
        before = self.maps(collection)
        report = {'lines': []}
        with patch.object(runtime, 'warn') as warn:
            self.assertTrue(importer.sync_collection_sids(collection, report))
        warn.assert_not_called()
        after = self.maps(collection)
        self.assertEqual({k: v.export_text() for k, v in after['reloading'].items()},
                         {k: v.export_text() for k, v in before['reloading'].items()})
        one_hand = after['one_hand_reloading']
        self.assertEqual(set(one_hand), {'GunGun_MagDefault', 'GunGun_MagExtended'})
        self.assertIsInstance(next(key for key in one_hand if key == 'GunGun_MagDefault'), Name)
        self.assertEqual(one_hand['GunGun_MagDefault'].export_text(),
                         before['one_hand_reloading']['GunUDP_MagDefault'].export_text())
        self.assertEqual(one_hand['GunGun_MagExtended'].export_text(),
                         before['one_hand_reloading']['GunUDP_MagIncreased'].export_text())
        attaching = after['attaching_by_sid']
        self.assertNotIn('EN_Silen_1', attaching)
        self.assertEqual(attaching['EN_Silen_2'].export_text(),
                         before['attaching_by_sid']['EN_Silen_1'].export_text())
        self.assertEqual(attaching['GunGun_MagDefault'].export_text(),
                         before['attaching_by_sid']['GunGun_MagDefault'].export_text())
        self.assertEqual(collection.get_editor_property('internal_animations').get_editor_property('shooting'),
                         {'loose': 'MG_shoot'})
        importer.library.save_loaded_asset.assert_called_once_with(collection)
        self.assertIn('collection one_hand_reloading: GunUDP_MagDefault -> GunGun_MagDefault (replaced)',
                      report['lines'])
        self.assertIn('collection attaching_by_sid: EN_Silen_1 -> EN_Silen_2 (replaced)', report['lines'])

    def test_existing_targets_are_preserved_and_old_duplicates_removed_in_every_map(self):
        importer, collection = self.make()
        internal = collection.get_editor_property('internal_animations')
        for field in runtime.COLLECTION_SID_MAPS:
            entries = internal.get_editor_property(field)
            entries[Name('GunUDP_MagDefault')] = reload_entry('MG_donor')
            entries[Name('GunGun_MagDefault')] = reload_entry('MG_custom')
            if field == 'attaching_by_sid':
                entries['EN_Silen_2'] = attach_entry('MG_custom_silencer')
                entries['UnrelatedAttachment'] = attach_entry('MG_unrelated')
            internal.set_editor_property(field, entries)
        collection.set_editor_property('internal_animations', internal)
        self.assertTrue(importer.sync_collection_sids(collection, {'lines': []}))
        for field, entries in self.maps(collection).items():
            self.assertNotIn('GunUDP_MagDefault', entries)
            self.assertEqual(entries['GunGun_MagDefault'].export_text(), reload_entry('MG_custom').export_text())
        entries = self.maps(collection)['attaching_by_sid']
        self.assertNotIn('EN_Silen_1', entries)
        self.assertEqual(entries['EN_Silen_2'].export_text(), attach_entry('MG_custom_silencer').export_text())
        self.assertEqual(entries['UnrelatedAttachment'].export_text(), attach_entry('MG_unrelated').export_text())

    def test_failed_save_restores_original_maps(self):
        importer, collection = self.make()
        before = collection.get_editor_property('internal_animations').export_text()
        importer.library.save_loaded_asset.return_value = False
        with patch.object(runtime, 'warn') as warn:
            self.assertFalse(importer.sync_collection_sids(collection, {'lines': []}))
        self.assertEqual(collection.get_editor_property('internal_animations').export_text(), before)
        self.assertIn('could not save', warn.call_args.args[0])

    def test_second_run_changes_nothing(self):
        importer, collection = self.make()
        importer.sync_collection_sids(collection, {'lines': []})
        importer.library.save_loaded_asset.reset_mock()
        self.assertFalse(importer.sync_collection_sids(collection, {'lines': []}))
        importer.library.save_loaded_asset.assert_not_called()

    def test_readback_mismatch_restores_original_and_does_not_save(self):
        importer, collection = self.make()
        before = collection.get_editor_property('internal_animations').export_text()
        with patch.object(runtime.Importer, 'collection_sids_match', return_value=False), \
                patch.object(runtime, 'warn') as warn:
            self.assertFalse(importer.sync_collection_sids(collection, {'lines': []}))
        self.assertEqual(collection.get_editor_property('internal_animations').export_text(), before)
        importer.library.save_loaded_asset.assert_not_called()
        warn.assert_called_once()

    def test_changed_existing_entry_fails_readback(self):
        importer, collection = self.make()
        original = collection.get_editor_property('internal_animations')
        internal = collection.get_editor_property('internal_animations')
        attaching = internal.get_editor_property('attaching_by_sid')
        attaching['EN_Silen_2'] = attaching['EN_Silen_1']
        attaching['EN_Silen_1'] = attach_entry('MG_other')
        internal.set_editor_property('attaching_by_sid', attaching)
        collection.set_editor_property('internal_animations', internal)
        self.assertFalse(runtime.Importer.collection_sids_match(
            collection, original, {'attaching_by_sid': {'EN_Silen_1': 'EN_Silen_2'}}))

    def test_silencer_without_template_entry_warns(self):
        importer, collection = self.make(attaching={'GunGun_MagDefault': attach_entry('MG_mag_attach')})
        with patch.object(runtime, 'warn') as warn:
            importer.sync_collection_sids(collection, {'lines': []})
        self.assertTrue(any('EN_Silen_2' in call.args[0] for call in warn.call_args_list))

    def test_no_magazines_or_attachments_leaves_collection_alone(self):
        importer, collection = self.make()
        importer.manifest = {}
        before = collection.get_editor_property('internal_animations').export_text()
        self.assertFalse(importer.sync_collection_sids(collection, {'lines': []}))
        self.assertEqual(collection.get_editor_property('internal_animations').export_text(), before)


class AttachmentNotify(Properties):
    def get_class(self):
        return SimpleNamespace(get_name=lambda: self.values.get('class_name', 'AnimNotify_AttachItem'))


class AttachmentNotifyTests(unittest.TestCase):
    PATH = '/Mod/Animations/Player/gun/Attaches/MG_fp_gun_silencer_attach'

    def setUp(self):
        self.unreal = SimpleNamespace(AnimationLibrary=SimpleNamespace(
            get_animation_notify_events=Mock(side_effect=lambda asset: asset.values['events'])))
        patcher = patch.object(runtime, 'unreal', self.unreal)
        patcher.start()
        self.addCleanup(patcher.stop)

    def make(self, sids=('EN_Silen_1', 'EN_Silen_1')):
        importer = runtime.Importer.__new__(runtime.Importer)
        importer.manifest = {
            'game_root': '/Mod', 'weapon': 'gun', 'magazines': CollectionSidTests.MAGAZINES,
            'attachments': [{'sid': 'EN_Silen_2', 'kind': 'silencer'}],
        }
        importer.library = SimpleNamespace(save_loaded_asset=Mock(return_value=True))
        notifies = [
            AttachmentNotify(path=self.PATH + '.MG_fp_gun_silencer_attach:Notify_' + str(index),
                             binded_attach_sid=Name(sid), attach_action=action)
            for index, (sid, action) in enumerate(zip(sids, ('join_hand', 'attach_weapon')))
        ]
        montage = Properties(path=self.PATH + '.MG_fp_gun_silencer_attach',
                             events=[Properties(notify=n) for n in notifies])
        return importer, montage, notifies

    def test_both_donor_silencer_notifies_use_configured_sid(self):
        importer, montage, notifies = self.make()
        report = {'lines': []}
        self.assertTrue(importer.sync_attachment_notifies(montage, report))
        self.assertEqual([n.get_editor_property('binded_attach_sid') for n in notifies],
                         ['EN_Silen_2', 'EN_Silen_2'])
        self.assertTrue(all(isinstance(n.get_editor_property('binded_attach_sid'), Name) for n in notifies))
        self.assertEqual([n.get_editor_property('attach_action') for n in notifies],
                         ['join_hand', 'attach_weapon'])
        importer.library.save_loaded_asset.assert_called_once_with(montage)
        self.unreal.AnimationLibrary.get_animation_notify_events.assert_called_once_with(montage)
        self.assertEqual(len(report['lines']), 2)
        self.assertIn('notify BindedAttachSid EN_Silen_1 -> EN_Silen_2', report['lines'][0])
        importer.library.save_loaded_asset.reset_mock()
        self.assertFalse(importer.sync_attachment_notifies(montage, {'lines': []}))
        importer.library.save_loaded_asset.assert_not_called()

    def test_magazine_notifies_follow_default_and_extended_roles(self):
        importer, montage, notifies = self.make(('GunUDP_MagDefault', 'GunUDP_MagIncreased'))
        self.assertTrue(importer.sync_attachment_notifies(montage, {'lines': []}))
        self.assertEqual([n.get_editor_property('binded_attach_sid') for n in notifies],
                         ['GunGun_MagDefault', 'GunGun_MagExtended'])

    def test_custom_silencer_sid_is_used(self):
        importer, montage, notifies = self.make()
        importer.manifest['attachments'] = [{'sid': 'GunGun_Silencer', 'kind': 'silencer'}]
        self.assertTrue(importer.sync_attachment_notifies(montage, {'lines': []}))
        self.assertEqual(notifies[0].get_editor_property('binded_attach_sid'), 'GunGun_Silencer')

    def test_unrelated_notifies_and_unbound_sids_are_untouched(self):
        importer, montage, notifies = self.make(('', 'UnknownAttachment'))
        notifies[1].values['class_name'] = 'AnimNotify_AkEvent_C'
        self.assertFalse(importer.sync_attachment_notifies(montage, {'lines': []}))
        self.assertEqual([n.get_editor_property('binded_attach_sid') for n in notifies],
                         ['', 'UnknownAttachment'])
        importer.library.save_loaded_asset.assert_not_called()

    def test_ambiguous_custom_silencers_warn_before_changing_anything(self):
        importer, montage, notifies = self.make()
        importer.manifest['attachments'] = [
            {'sid': sid, 'kind': 'silencer'} for sid in ('CustomA', 'CustomB')]
        with patch.object(runtime, 'warn') as warn:
            self.assertFalse(importer.sync_attachment_notifies(montage, {'lines': []}))
        self.assertEqual(notifies[0].get_editor_property('binded_attach_sid'), 'EN_Silen_1')
        self.assertIn('multiple silencer replacements', warn.call_args.args[0])
        importer.library.save_loaded_asset.assert_not_called()

    def test_bad_readback_restores_both_notifies_without_saving(self):
        importer, montage, notifies = self.make()
        setter = notifies[1].set_editor_property
        notifies[1].set_editor_property = lambda field, value: setter(
            field, Name('wrong') if value == 'EN_Silen_2' else value)
        with patch.object(runtime, 'warn') as warn:
            self.assertFalse(importer.sync_attachment_notifies(montage, {'lines': []}))
        self.assertEqual([n.get_editor_property('binded_attach_sid') for n in notifies],
                         ['EN_Silen_1', 'EN_Silen_1'])
        self.assertIn('did not read back', warn.call_args.args[0])
        importer.library.save_loaded_asset.assert_not_called()

    def test_failed_save_restores_notifies_and_warns(self):
        importer, montage, notifies = self.make()
        importer.library.save_loaded_asset.return_value = False
        with patch.object(runtime, 'warn') as warn:
            self.assertFalse(importer.sync_attachment_notifies(montage, {'lines': []}))
        self.assertEqual([n.get_editor_property('binded_attach_sid') for n in notifies],
                         ['EN_Silen_1', 'EN_Silen_1'])
        self.assertIn('could not save', warn.call_args.args[0])

    def test_shared_montage_is_rejected(self):
        importer, montage, notifies = self.make()
        montage.values['path'] = '/Game/Attaches/MG_fp_udp_silencer_attach.MG_fp_udp_silencer_attach'
        with self.assertRaisesRegex(RuntimeError, 'mod-owned'):
            importer.sync_attachment_notifies(montage, {'lines': []})
        self.assertEqual(notifies[0].get_editor_property('binded_attach_sid'), 'EN_Silen_1')
        importer.library.save_loaded_asset.assert_not_called()

    def test_notify_update_runs_when_sequence_repoint_changes_nothing(self):
        importer, montage, notifies = self.make()
        importer.counts = {}
        importer.mod_assets = lambda: {'montage': {self.PATH.lower(): self.PATH}, 'collection': {}}
        importer.library.load_asset = Mock(return_value=montage)
        importer.repoint_montage = Mock(return_value=False)
        with patch.object(runtime, 'warn'), patch.object(runtime, 'log'):
            importer.update_montages()
        self.assertEqual(notifies[0].get_editor_property('binded_attach_sid'), 'EN_Silen_2')
        self.assertEqual(importer.counts['montages/collections updated'], 1)


if __name__ == '__main__':
    unittest.main()
