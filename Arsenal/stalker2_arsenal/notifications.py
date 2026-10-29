from functools import wraps
import textwrap

import bpy


_operations = []


def report(operator, levels, message):
    for operation in _operations:
        if 'ERROR' in levels:
            operation['severity'] = 'ERROR'
        elif 'WARNING' in levels and operation['severity'] != 'ERROR':
            operation['severity'] = 'WARNING'
        operation['message'] = message
    operator.report(levels, message)


def notify(context, title, message, severity):
    print(f'[Arsenal] {title}: {message}')
    if bpy.app.background:
        return

    def draw(self, _context):
        for line in message.splitlines():
            for wrapped in textwrap.wrap(line, width=90):
                self.layout.label(text=wrapped)
        self.layout.label(text='See the report log / system console for details.')

    icon = 'INFO' if severity == 'INFO' else 'ERROR'
    context.window_manager.popup_menu(draw, title=title, icon=icon)


def completion(title):
    def decorate(execute):
        @wraps(execute)
        def wrapped(self, context):
            outermost = not _operations
            operation = {'severity': 'INFO', 'message': ''}
            _operations.append(operation)
            try:
                result = execute(self, context)
                if 'FINISHED' not in result:
                    operation['severity'] = 'ERROR'
                return result
            except Exception as error:
                operation.update(severity='ERROR', message=str(error))
                raise
            finally:
                _operations.pop()
                if outermost:
                    severity = operation['severity']
                    status = {'INFO': 'complete', 'WARNING': 'finished with warnings',
                              'ERROR': 'failed'}[severity]
                    notify(context, f'{title} {status}',
                           operation['message'] or 'See the report log for details.', severity)
        return wrapped
    return decorate
