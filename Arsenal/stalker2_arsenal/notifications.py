from functools import wraps
import textwrap
import time

import bpy


_operations = []


def _duration(seconds):
    minutes, seconds = divmod(int(round(seconds)), 60)
    return f'{minutes}:{seconds:02d}'


class Progress:
    """Mouse-cursor percentage plus a console line per item, e.g. `Importing: 65% (42/64 idle, ...)`.

    Blender does not redraw the status bar during a long operator, and its cursor number has a fixed
    `65.00` format, so the system console is where artists can read the labelled progress."""

    def __init__(self, context, total, label, clock=time.monotonic):
        self.window_manager = getattr(context, 'window_manager', None)
        self.total = total
        self.label = label
        self.clock = clock
        self.done = 0

    def __enter__(self):
        self.start = self.clock()
        if self.window_manager is not None and self.total:
            self.window_manager.progress_begin(0, 100)
        print(f'[Arsenal] {self.label}: {self.total} to do. Progress is shown here; Blender may look frozen.',
              flush=True)
        return self

    def percent(self):
        return round(100 * self.done / self.total) if self.total else 100

    def message(self, name):
        elapsed = self.clock() - self.start
        text = (f'[Arsenal] {self.label}: {self.percent()}% ({self.done + 1}/{self.total} {name}, '
                f'elapsed {_duration(elapsed)}')
        if self.done:
            text += f', about {_duration(elapsed / self.done * (self.total - self.done))} left'
        return text + ')'

    def step(self, name):
        print(self.message(name), flush=True)
        if self.window_manager is not None and self.total:
            self.window_manager.progress_update(self.percent())
        self.done += 1

    def __exit__(self, *_error):
        if self.window_manager is not None and self.total:
            self.window_manager.progress_end()
        print(f'[Arsenal] {self.label}: finished {self.done}/{self.total} in {_duration(self.clock() - self.start)}',
              flush=True)
        return False


def report(operator, levels, message):
    for operation in _operations:
        if 'ERROR' in levels:
            operation['severity'] = 'ERROR'
        elif 'WARNING' in levels and operation['severity'] != 'ERROR':
            operation['severity'] = 'WARNING'
        operation['message'] = message
        operation['reported'] = True
        if 'ERROR' in levels:
            operation['blender_popup'] = True
    operator.report(levels, message)


def notify(context, title, message, severity, log=True, popup=True):
    """`log`/`popup` are off when Blender already shows the same message, so it appears once."""
    if log:
        print(f'[Arsenal] {title}: {message}')
    if bpy.app.background or not popup:
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
            operation = {'severity': 'INFO', 'message': '', 'reported': False, 'blender_popup': False,
                         'finished': False}
            _operations.append(operation)
            try:
                result = execute(self, context)
                operation['finished'] = 'FINISHED' in result
                if not operation['finished']:
                    operation['severity'] = 'ERROR'
                return result
            except Exception as error:
                # Blender reports an operator exception as an error popup and prints its traceback.
                operation.update(severity='ERROR', message=str(error), reported=False, blender_popup=True)
                raise
            finally:
                _operations.pop()
                if outermost:
                    severity = operation['severity']
                    status = {'INFO': 'complete', 'WARNING': 'finished with warnings',
                              'ERROR': 'failed'}[severity]
                    # Blender logs a finished operator's reports to the console and pops up any ERROR report.
                    notify(context, f'{title} {status}',
                           operation['message'] or 'See the report log for details.', severity,
                           log=not (operation['reported'] and operation['finished']),
                           popup=not operation['blender_popup'])
        return wrapped
    return decorate
