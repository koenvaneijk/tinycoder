import unittest
from unittest.mock import MagicMock, patch, call
import logging

from tinycoder.shell_executor import ShellExecutor
from tinycoder.chat_history import ChatHistoryManager


class TestShellExecutor(unittest.TestCase):

    def setUp(self):
        self.mock_logger = MagicMock(spec=logging.Logger)
        self.mock_history_manager = MagicMock(spec=ChatHistoryManager)
        self.git_root = "/fake/git/root"
        self.executor = ShellExecutor(self.mock_logger, self.mock_history_manager, self.git_root)

    def test_init(self):
        self.assertIs(self.executor.logger, self.mock_logger)
        self.assertIs(self.executor.history_manager, self.mock_history_manager)
        self.assertEqual(self.executor.git_root, self.git_root)

    def test_execute_empty_command(self):
        result = self.executor.execute("!", False)
        self.mock_logger.error.assert_called_once_with("Usage: !<shell_command>")
        self.assertTrue(result)

    def test_execute_command_with_only_spaces(self):
        result = self.executor.execute("! ", False)
        self.mock_logger.error.assert_called_once_with("Usage: !<shell_command>")
        self.assertTrue(result)

    @patch('tinycoder.shell_executor.subprocess.run')
    @patch('tinycoder.shell_executor.Path')
    def test_execute_successful_command(self, mock_path_class, mock_subprocess_run):
        mock_subprocess_run.return_value.stdout = "output"
        mock_subprocess_run.return_value.stderr = ""
        mock_subprocess_run.return_value.returncode = 0

        mock_cwd_path = MagicMock()
        mock_path_class.return_value = mock_cwd_path

        with patch('builtins.print') as mock_print, \
             patch('builtins.input', return_value='n') as mock_input:
            result = self.executor.execute("!echo test", False)

        self.mock_logger.info.assert_any_call(f"Executing shell command: echo test")
        mock_subprocess_run.assert_called_once_with(
            ['echo', 'test'],
            capture_output=True,
            text=True,
            check=False,
            cwd=mock_cwd_path
        )
        mock_print.assert_any_call("--- Shell Command Output ---")
        mock_print.assert_any_call("output")
        mock_print.assert_any_call("--- End Shell Command Output ---")
        self.mock_history_manager.add_message.assert_not_called()
        self.assertTrue(result)

    @patch('tinycoder.shell_executor.subprocess.run')
    @patch('tinycoder.shell_executor.Path')
    def test_execute_command_with_non_zero_exit_code(self, mock_path_class, mock_subprocess_run):
        mock_subprocess_run.return_value.stdout = "output"
        mock_subprocess_run.return_value.stderr = "error message"
        mock_subprocess_run.return_value.returncode = 1

        mock_cwd_path = MagicMock()
        mock_path_class.return_value = mock_cwd_path

        with patch('builtins.print') as mock_print, \
             patch('builtins.input', return_value='n') as mock_input:
            result = self.executor.execute("!ls nonexistent", False)

        self.mock_logger.warning.assert_called_once_with("Shell command 'ls nonexistent' exited with code 1")
        self.assertTrue(result)

    @patch('tinycoder.shell_executor.subprocess.run')
    @patch('tinycoder.shell_executor.Path')
    def test_execute_command_user_chooses_to_add_to_context(self, mock_path_class, mock_subprocess_run):
        mock_subprocess_run.return_value.stdout = "output"
        mock_subprocess_run.return_value.stderr = ""
        mock_subprocess_run.return_value.returncode = 0

        mock_cwd_path = MagicMock()
        mock_path_class.return_value = mock_cwd_path

        with patch('builtins.print') as mock_print, \
             patch('builtins.input', return_value='y') as mock_input:
            result = self.executor.execute("!echo test", False)

        self.mock_history_manager.add_message.assert_called_once_with(
            "tool", "Output of shell command: `echo test`\n--- stdout ---\noutput"
        )
        self.mock_logger.info.assert_called_with("Shell command output added to chat context.")
        self.assertTrue(result)

    @patch('tinycoder.shell_executor.subprocess.run')
    @patch('tinycoder.shell_executor.Path')
    def test_execute_command_in_non_interactive_mode(self, mock_path_class, mock_subprocess_run):
        mock_subprocess_run.return_value.stdout = "output"
        mock_subprocess_run.return_value.stderr = ""
        mock_subprocess_run.return_value.returncode = 0

        mock_cwd_path = MagicMock()
        mock_path_class.return_value = mock_cwd_path

        with patch('builtins.print') as mock_print:
            result = self.executor.execute("!echo test", True)

        self.mock_history_manager.add_message.assert_not_called()
        self.assertTrue(result)

    @patch('tinycoder.shell_executor.subprocess.run')
    @patch('tinycoder.shell_executor.Path')
    def test_execute_command_file_not_found_error(self, mock_path_class, mock_subprocess_run):
        mock_subprocess_run.side_effect = FileNotFoundError

        mock_cwd_path = MagicMock()
        mock_path_class.return_value = mock_cwd_path

        with patch('builtins.print') as mock_print:
            result = self.executor.execute("!nonexistentcommand", False)

        self.mock_logger.error.assert_called_once_with("Shell command not found: nonexistentcommand")
        self.assertTrue(result)

    @patch('tinycoder.shell_executor.subprocess.run')
    @patch('tinycoder.shell_executor.Path')
    def test_execute_command_generic_exception_during_subprocess(self, mock_path_class, mock_subprocess_run):
        mock_subprocess_run.side_effect = Exception("Generic error")

        mock_cwd_path = MagicMock()
        mock_path_class.return_value = mock_cwd_path

        with patch('builtins.print') as mock_print:
            result = self.executor.execute("!echo test", False)

        self.mock_logger.error.assert_called_once()
        self.assertIn("Error executing shell command 'echo test': Generic error", self.mock_logger.error.call_args[0][0])
        self.assertTrue(result)

    @patch('tinycoder.shell_executor.subprocess.run')
    @patch('tinycoder.shell_executor.Path')
    def test_execute_command_user_input_eof_error(self, mock_path_class, mock_subprocess_run):
        mock_subprocess_run.return_value.stdout = "output"
        mock_subprocess_run.return_value.stderr = ""
        mock_subprocess_run.return_value.returncode = 0

        mock_cwd_path = MagicMock()
        mock_path_class.return_value = mock_cwd_path

        with patch('builtins.print') as mock_print, \
             patch('builtins.input', side_effect=EOFError) as mock_input:
            result = self.executor.execute("!echo test", False)

        self.mock_history_manager.add_message.assert_not_called()
        self.assertTrue(result)

    @patch('tinycoder.shell_executor.subprocess.run')
    @patch('tinycoder.shell_executor.Path')
    def test_execute_command_user_input_keyboard_interrupt(self, mock_path_class, mock_subprocess_run):
        mock_subprocess_run.return_value.stdout = "output"
        mock_subprocess_run.return_value.stderr = ""
        mock_subprocess_run.return_value.returncode = 0

        mock_cwd_path = MagicMock()
        mock_path_class.return_value = mock_cwd_path

        with patch('builtins.print') as mock_print, \
             patch('builtins.input', side_effect=KeyboardInterrupt) as mock_input:
            result = self.executor.execute("!echo test", False)

        self.mock_logger.info.assert_any_call("\nShell output addition to context cancelled.")
        self.mock_history_manager.add_message.assert_not_called()
        self.assertTrue(result)


if __name__ == '__main__':
    unittest.main()