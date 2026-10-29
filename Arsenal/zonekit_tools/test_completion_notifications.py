"""Run with Python: completion reporting without opening Blender or ZoneKit."""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).parents[1] / 'stalker2_arsenal'


def load(name):
    spec = importlib.util.spec_from_file_location('test_' + name, ROOT / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


with patch.dict(sys.modules, {'bpy': SimpleNamespace(app=SimpleNamespace(background=False))}):
    blender = load('notifications')
setup = load('unreal_setup')
importer = load('unreal_import')


class BlenderNotificationTests(unittest.TestCase):
    def setUp(self):
        self.context = SimpleNamespace(window_manager=SimpleNamespace(popup_menu=Mock()))
        self.operator = SimpleNamespace(report=Mock())
        self.notify = patch.object(blender, 'notify')
        self.popup = self.notify.start()
        self.addCleanup(self.notify.stop)

    def test_success(self):
        @blender.completion('Import')
        def execute(operator, context):
            blender.report(operator, {'INFO'}, 'Imported 12 clips.')
            return {'FINISHED'}

        self.assertEqual(execute(self.operator, self.context), {'FINISHED'})
        self.popup.assert_called_once_with(
            self.context, 'Import complete', 'Imported 12 clips.', 'INFO')
        self.operator.report.assert_called_once()

    def test_nested_warning_produces_one_outer_notification(self):
        @blender.completion('Nested import')
        def child(operator, context):
            blender.report(operator, {'WARNING'}, 'One clip skipped.')
            return {'FINISHED'}

        @blender.completion('Weapon import')
        def parent(operator, context):
            child(operator, context)
            blender.report(operator, {'INFO'}, 'Weapon imported.')
            return {'FINISHED'}

        parent(self.operator, self.context)
        self.popup.assert_called_once_with(
            self.context, 'Weapon import finished with warnings', 'Weapon imported.', 'WARNING')
        self.assertEqual(blender._operations, [])

    def test_cancelled(self):
        @blender.completion('Export')
        def execute(operator, context):
            blender.report(operator, {'ERROR'}, 'Missing rig.')
            return {'CANCELLED'}

        self.assertEqual(execute(self.operator, self.context), {'CANCELLED'})
        self.assertEqual(self.popup.call_args.args[1:], ('Export failed', 'Missing rig.', 'ERROR'))

    def test_exception_is_not_swallowed_and_next_operation_is_clean(self):
        @blender.completion('Retarget')
        def execute(operator, context):
            raise RuntimeError('Bake failed')

        with self.assertRaisesRegex(RuntimeError, 'Bake failed'):
            execute(self.operator, self.context)
        self.popup.assert_called_once_with(self.context, 'Retarget failed', 'Bake failed', 'ERROR')
        self.assertEqual(blender._operations, [])

    def test_headless_logs_without_popup(self):
        with patch.object(blender.bpy.app, 'background', True), patch('builtins.print') as log:
            self.notify.stop()
            blender.notify(self.context, 'Export complete', 'Done', 'INFO')
        log.assert_called_once()
        self.context.window_manager.popup_menu.assert_not_called()

    def test_interactive_popup(self):
        self.notify.stop()
        blender.notify(self.context, 'Export complete', 'Done', 'INFO')
        self.context.window_manager.popup_menu.assert_called_once()
        self.assertEqual(self.context.window_manager.popup_menu.call_args.kwargs,
                         {'title': 'Export complete', 'icon': 'INFO'})

    def test_warning_popup_uses_blender_error_icon(self):
        self.notify.stop()
        blender.notify(self.context, 'Export finished with warnings', 'Check logs', 'WARNING')
        self.assertEqual(self.context.window_manager.popup_menu.call_args.kwargs['icon'], 'ERROR')


class ZoneKitNotificationTests(unittest.TestCase):
    def unreal(self):
        return SimpleNamespace(
            EditorDialog=SimpleNamespace(show_message=Mock()),
            AppMsgCategory=SimpleNamespace(INFO='info', WARNING='warning', ERROR='error'),
            AppMsgType=SimpleNamespace(OK='ok'), log_error=Mock(), log_warning=Mock())

    def test_success_and_warning_for_both_scripts(self):
        for module, title in ((setup, 'setup'), (importer, 'import')):
            for warning in (False, True):
                with self.subTest(script=title, warning=warning):
                    unreal = self.unreal()

                    def work(*args):
                        if warning:
                            module.warn('Skipped an asset')

                    with patch.object(module, 'unreal', unreal), patch.object(module, '_main', work):
                        module.main()
                    unreal.EditorDialog.show_message.assert_called_once()
                    call = unreal.EditorDialog.show_message.call_args
                    status = 'finished with warnings' if warning else 'complete'
                    self.assertEqual(call.args[0], f'Arsenal {title} {status}')
                    self.assertEqual(call.kwargs['message_category'], 'warning' if warning else 'info')

    def test_failures_notify_and_reraise_for_both_scripts(self):
        for module in (setup, importer):
            unreal = self.unreal()
            with patch.object(module, 'unreal', unreal), patch.object(
                    module, '_main', side_effect=RuntimeError('Import failed')):
                with self.assertRaisesRegex(RuntimeError, 'Import failed'):
                    module.main()
            unreal.EditorDialog.show_message.assert_called_once()
            self.assertEqual(unreal.EditorDialog.show_message.call_args.kwargs['message_category'], 'error')
            unreal.log_error.assert_called_once()

    def test_import_dry_run_does_not_notify(self):
        unreal = self.unreal()
        with patch.object(importer, 'unreal', unreal), patch.object(importer, '_main'):
            importer.main(['--dry-run'])
        unreal.EditorDialog.show_message.assert_not_called()

    def test_setup_dry_run_message(self):
        unreal = self.unreal()
        with patch.object(setup, 'unreal', unreal), patch.object(
                setup, 'CONFIG', {'dry_run': True}), patch.object(setup, '_main'):
            setup.main()
        self.assertIn('Dry run', unreal.EditorDialog.show_message.call_args.args[1])


if __name__ == '__main__':
    unittest.main()
