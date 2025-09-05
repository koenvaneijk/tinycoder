import unittest
from unittest.mock import patch, mock_open, MagicMock
from pathlib import Path
import logging
# from typing import Any # No longer needed after removing path_exists_logic_wrapper

from tinycoder.docker_manager import DockerManager

# Disable logging for tests
logging.disable(logging.CRITICAL)

class TestDockerManager(unittest.TestCase):
    """Test suite for the DockerManager class."""

    def setUp(self: 'TestDockerManager') -> None:
        """Set up for test methods."""
        self.mock_logger = MagicMock(spec=logging.Logger)
        self.test_root_dir = Path("/fake/project/root")

    def _create_manager(
        self: 'TestDockerManager',
        root_dir: Path | None = None,
        check_docker_availability_return: bool = True,
        yml_exists: bool = False, # Specific control for docker-compose.yml
        yaml_exists: bool = False, # Specific control for docker-compose.yaml
        compose_content: str = ""
    ) -> DockerManager:
        """Helper to create a DockerManager instance with mocks."""

        exists_call_results = []
        if root_dir: # Only prepare results if root_dir is provided, as Path.exists calls depend on it
            # DockerManager.__init__ logic for compose file:
            # 1. Checks (root_dir / 'docker-compose.yml').exists()
            # 2. If 1 is False, it then checks (root_dir / 'docker-compose.yaml').exists()
            #    after setting self.compose_file to the .yaml path.
            # 3. Finally, it checks self.compose_file.exists() one more time before parsing.
            #    This means if .yml exists, sequence is [True, True] for its two checks.
            #    If .yml no, .yaml yes, sequence is [False, True] for .yml then .yaml.
            #    If .yml no, .yaml no, sequence is [False, False] for .yml then .yaml.

            # Call 1: on 'docker-compose.yml'
            exists_call_results.append(yml_exists)

            if yml_exists:
                # If .yml exists, it's chosen. The final check is on this .yml file.
                exists_call_results.append(True)
            else:
                # If .yml does not exist, .yaml is tried. Call 2 is on 'docker-compose.yaml'.
                exists_call_results.append(yaml_exists)
        
        # If exists_call_results is empty (e.g. root_dir is None), 
        # Path.exists mock will use default MagicMock behavior if called,
        # but DockerManager shouldn't call .exists() on compose files in that case.

        should_mock_open = (yml_exists or yaml_exists) and compose_content is not None
        
        # Ensure that Path.exists is patched with a side_effect that provides enough values
        # for the expected calls during DockerManager initialization.
        # If fewer calls are made than items in exists_call_results, it's fine.
        # If more calls are made, the mock will raise an error after exhausting the list,
        # or use default MagicMock behavior if side_effect was not a list (not the case here).
        path_exists_patch = patch('pathlib.Path.exists', side_effect=exists_call_results)

        with patch.object(DockerManager, '_check_docker_availability', return_value=check_docker_availability_return), \
             path_exists_patch:
            if should_mock_open:
                with patch('builtins.open', mock_open(read_data=compose_content)):
                    manager = DockerManager(root_dir, self.mock_logger)
            else:
                manager = DockerManager(root_dir, self.mock_logger)
        
        return manager

    # --- Tests for _parse_yaml_simple ---

    def test_parse_yaml_simple_basic(self: 'TestDockerManager') -> None:
        """Test _parse_yaml_simple with basic key-value pairs."""
        manager = self._create_manager(root_dir=self.test_root_dir) # yml_exists=False, yaml_exists=False by default
        yaml_content = """
version: '3.8'
services:
  web:
    image: nginx
    ports:
      - "80:80"
"""
        expected = {
            'version': "'3.8'",
            'services': {
                'web': {
                    'image': 'nginx',
                    'ports': ['"80:80"']
                }
            }
        }
        self.assertEqual(manager._parse_yaml_simple(yaml_content), expected)

    def test_parse_yaml_simple_with_comments_and_blank_lines(self: 'TestDockerManager') -> None:
        """Test _parse_yaml_simple handles comments and blank lines."""
        manager = self._create_manager(root_dir=self.test_root_dir)
        yaml_content = """
# This is a comment
version: '3.9'

services: # Another comment
  # Service definition
  app:
    build: . # Build context
    # ports:
    #  - "5000:5000"
"""
        expected = {
            'version': "'3.9'",
            'services': {
                'app': {
                    'build': '.'
                }
            }
        }
        self.assertEqual(manager._parse_yaml_simple(yaml_content), expected)

    def test_parse_yaml_simple_list_of_strings(self: 'TestDockerManager') -> None:
        """Test _parse_yaml_simple with a list of strings."""
        manager = self._create_manager(root_dir=self.test_root_dir)
        yaml_content = """
environment:
  - DEBUG=1
  - PYTHONUNBUFFERED=1
"""
        expected = {'environment': ['DEBUG=1', 'PYTHONUNBUFFERED=1']}
        self.assertEqual(manager._parse_yaml_simple(yaml_content), expected)

    def test_parse_yaml_simple_deeply_nested(self: 'TestDockerManager') -> None:
        """Test _parse_yaml_simple with deeply nested structures."""
        manager = self._create_manager(root_dir=self.test_root_dir)
        yaml_content = """
x-logging: &logging
  driver: "json-file"
  options:
    max-size: "10m"
    max-file: "3"

services:
  api:
    logging: *logging
"""
        # Our simple parser won't handle YAML anchors/aliases like *logging
        # It will parse it as a string if on same line, or as nested if indented
        expected_simplified = {
            'x-logging': {
                'driver': '"json-file"',
                'options': {
                    'max-size': '"10m"',
                    'max-file': '"3"'
                }
            },
            'services': {
                'api': {
                    'logging': '*logging' # Parsed as a string value
                }
            }
        }
        self.assertEqual(manager._parse_yaml_simple(yaml_content), expected_simplified)


    def test_parse_yaml_simple_empty_input(self: 'TestDockerManager') -> None:
        """Test _parse_yaml_simple with empty input."""
        manager = self._create_manager(root_dir=self.test_root_dir)
        self.assertIsNone(manager._parse_yaml_simple(""))

    def test_parse_yaml_simple_only_comments(self: 'TestDockerManager') -> None:
        """Test _parse_yaml_simple with input containing only comments."""
        manager = self._create_manager(root_dir=self.test_root_dir)
        yaml_content = """
# comment 1
# comment 2
"""
        self.assertIsNone(manager._parse_yaml_simple(yaml_content))

    def test_parse_yaml_simple_mixed_indentation_in_list_skips_bad_lines(self: 'TestDockerManager') -> None:
        """Test _parse_yaml_simple with mixed indentation in a list (should skip bad lines)."""
        manager = self._create_manager(root_dir=self.test_root_dir)
        yaml_content = """
mylist:
  - item1
    - nested_under_item1_incorrectly_for_simple_parser # This should be skipped by current logic
  - item2
"""
        expected = {
            'mylist': ['item1', 'item2'] # 'nested_under_item1_incorrectly_for_simple_parser' is skipped
        }
        # The logger mock would show a warning
        parsed_result = manager._parse_yaml_simple(yaml_content)
        self.assertEqual(parsed_result, expected)
        self.mock_logger.warning.assert_called_with("YAML parser: Unexpected indent in list, skipping line: '- nested_under_item1_incorrectly_for_simple_parser'")


    # --- Tests for __init__ ---
    @patch.object(DockerManager, '_parse_compose_file')
    def test_init_docker_not_available(self: 'TestDockerManager', mock_parse_compose: MagicMock) -> None:
        """Test __init__ when Docker is not available."""
        manager = self._create_manager(root_dir=self.test_root_dir, check_docker_availability_return=False)
        self.assertFalse(manager.is_available)
        self.mock_logger.debug.assert_any_call("Docker command not found or daemon not running. DockerManager disabled.")
        mock_parse_compose.assert_not_called()

    @patch.object(DockerManager, '_parse_compose_file')
    def test_init_no_root_dir(self: 'TestDockerManager', mock_parse_compose: MagicMock) -> None:
        """Test __init__ when Docker is available but no root_dir is provided."""
        manager = self._create_manager(root_dir=None, yml_exists=False, yaml_exists=False)
        self.assertTrue(manager.is_available) # Docker itself is available
        self.assertIsNone(manager.root_dir)
        self.assertIsNone(manager.compose_file)
        self.mock_logger.debug.assert_any_call("No project root provided. Cannot locate docker-compose.yml.")
        mock_parse_compose.assert_not_called()

    @patch.object(DockerManager, '_parse_compose_file')
    def test_init_no_compose_file(self: 'TestDockerManager', mock_parse_compose: MagicMock) -> None:
        """Test __init__ when root_dir is provided but no compose file exists."""
        manager = self._create_manager(root_dir=self.test_root_dir, yml_exists=False, yaml_exists=False)
        self.assertTrue(manager.is_available)
        self.assertEqual(manager.root_dir, self.test_root_dir)
        self.assertIsNone(manager.compose_file)
        self.mock_logger.debug.assert_any_call("No docker-compose.yml or docker-compose.yaml found in project root.")
        mock_parse_compose.assert_not_called()

    def test_init_with_compose_file_yml(self: 'TestDockerManager') -> None:
        """Test __init__ with a docker-compose.yml file."""
        compose_content = "version: '3.8'\nservices:\n  app:\n    image: myapp"
        
        manager = self._create_manager(
            root_dir=self.test_root_dir,
            yml_exists=True,
            yaml_exists=False, # Ensure .yml is chosen if both could exist
            compose_content=compose_content
        )

        self.assertTrue(manager.is_available)
        self.assertEqual(manager.compose_file, self.test_root_dir / 'docker-compose.yml')
        self.assertIn('app', manager.services)
        self.mock_logger.debug.assert_any_call(f"Found docker-compose file: {self.test_root_dir / 'docker-compose.yml'}")

    def test_init_with_compose_file_yaml(self: 'TestDockerManager') -> None:
        """Test __init__ with a docker-compose.yaml file (when .yml is not present)."""
        compose_content = "version: '3.8'\nservices:\n  db:\n    image: postgres"

        manager = self._create_manager(
            root_dir=self.test_root_dir,
            yml_exists=False, # .yml does not exist
            yaml_exists=True,  # .yaml exists
            compose_content=compose_content
        )

        self.assertTrue(manager.is_available)
        self.assertEqual(manager.compose_file, self.test_root_dir / 'docker-compose.yaml')
        self.assertIn('db', manager.services)
        self.mock_logger.debug.assert_any_call(f"Found docker-compose file: {self.test_root_dir / 'docker-compose.yaml'}")


    # --- Tests for find_affected_services ---
    def test_find_affected_services_by_volume(self: 'TestDockerManager') -> None:
        """Test find_affected_services identifies services via volume mounts."""
        compose_content = """
services:
  web:
    image: nginx
    volumes:
      - ./html:/usr/share/nginx/html
  api:
    image: python
    volumes:
      - ./app:/app
"""
        manager = self._create_manager(root_dir=self.test_root_dir, yml_exists=True, compose_content=compose_content)
        
        modified_files = [self.test_root_dir / "html" / "index.html"]
        affected = manager.find_affected_services(modified_files)
        self.assertEqual(affected, {"web": {"volume"}})

        modified_files = [self.test_root_dir / "app" / "main.py"]
        affected = manager.find_affected_services(modified_files)
        self.assertEqual(affected, {"api": {"volume"}})

    def test_find_affected_services_by_build_context_str(self: 'TestDockerManager') -> None:
        """Test find_affected_services identifies services via string build context."""
        compose_content = """
services:
  builder:
    build: ./service_src
"""
        manager = self._create_manager(root_dir=self.test_root_dir, yml_exists=True, compose_content=compose_content)
        modified_files = [self.test_root_dir / "service_src" / "Dockerfile"]
        affected = manager.find_affected_services(modified_files)
        self.assertEqual(affected, {"builder": {"build_context"}})

    def test_find_affected_services_by_build_context_dict(self: 'TestDockerManager') -> None:
        """Test find_affected_services identifies services via dict build context."""
        compose_content = """
services:
  builder:
    build:
      context: ./app_code
      dockerfile: Dockerfile.dev
"""
        manager = self._create_manager(root_dir=self.test_root_dir, yml_exists=True, compose_content=compose_content)
        modified_files = [self.test_root_dir / "app_code" / "requirements.txt"]
        affected = manager.find_affected_services(modified_files)
        self.assertEqual(affected, {"builder": {"build_context"}})

    def test_find_affected_services_no_match(self: 'TestDockerManager') -> None:
        """Test find_affected_services when no services are affected."""
        compose_content = """
services:
  web:
    image: nginx
    volumes:
      - ./html:/usr/share/nginx/html
"""
        manager = self._create_manager(root_dir=self.test_root_dir, yml_exists=True, compose_content=compose_content)
        modified_files = [self.test_root_dir / "other_dir" / "somefile.txt"]
        affected = manager.find_affected_services(modified_files)
        self.assertEqual(affected, {})
    
    def test_find_affected_services_both_volume_and_build(self: 'TestDockerManager') -> None:
        """Test find_affected_services when a file affects both volume and build context of a service."""
        compose_content = """
services:
  app:
    build: ./app_source
    volumes:
      - ./app_source:/opt/app 
"""
        manager = self._create_manager(root_dir=self.test_root_dir, yml_exists=True, compose_content=compose_content)
        modified_files = [self.test_root_dir / "app_source" / "main.py"]
        affected = manager.find_affected_services(modified_files)
        self.assertEqual(affected, {"app": {"volume", "build_context"}})


    # --- Tests for has_live_reload ---
    def test_has_live_reload_command_flag(self: 'TestDockerManager') -> None:
        """Test has_live_reload via command flags."""
        compose_content = """
services:
  uvicorn_app:
    command: uvicorn main:app --reload
  flask_app:
    command: flask run --host=0.0.0.0
  node_app:
    command: nodemon index.js
  other_app:
    command: python run.py --watch
"""
        manager = self._create_manager(root_dir=self.test_root_dir, yml_exists=True, compose_content=compose_content)
        self.assertTrue(manager.has_live_reload("uvicorn_app"))
        # FLASK_ENV=development is usually in environment, not command for `flask run`
        self.assertFalse(manager.has_live_reload("flask_app")) # Add test for env var
        self.assertTrue(manager.has_live_reload("node_app"))
        self.assertTrue(manager.has_live_reload("other_app"))

    def test_has_live_reload_environment_var(self: 'TestDockerManager') -> None:
        """Test has_live_reload via environment variables."""
        compose_content = """
services:
  flask_dev:
    image: python
    environment:
      - FLASK_ENV=development
      - OTHER_VAR=foo
  another_app:
    image: custom
    environment:
      MY_RELOAD_VAR: --reload # This heuristic might be too broad if not careful
"""
        manager = self._create_manager(root_dir=self.test_root_dir, yml_exists=True, compose_content=compose_content)
        self.assertTrue(manager.has_live_reload("flask_dev"))
        self.assertTrue(manager.has_live_reload("another_app")) # Assuming --reload in env value is a signal

    def test_has_live_reload_command_list(self: 'TestDockerManager') -> None:
        """Test has_live_reload when command is a list."""
        compose_content = """
services:
  app_list_cmd:
    command:
      - uvicorn
      - main:app
      - --reload
"""
        manager = self._create_manager(root_dir=self.test_root_dir, yml_exists=True, compose_content=compose_content)
        self.assertTrue(manager.has_live_reload("app_list_cmd"))

    def test_has_live_reload_no_indicator(self: 'TestDockerManager') -> None:
        """Test has_live_reload when no indicators are present."""
        compose_content = """
services:
  prod_app:
    command: gunicorn main:app
    environment:
      - PROD=true
"""
        manager = self._create_manager(root_dir=self.test_root_dir, yml_exists=True, compose_content=compose_content)
        self.assertFalse(manager.has_live_reload("prod_app"))
        self.assertFalse(manager.has_live_reload("non_existent_service"))


    # --- Tests for Docker CLI interactions (mocking _run_command) ---
    @patch.object(DockerManager, '_run_command')
    def test_is_service_running_true(self: 'TestDockerManager', mock_run_command: MagicMock) -> None:
        """Test is_service_running returns True when service is up."""
        mock_run_command.return_value = (True, "container_id_output", "")
        manager = self._create_manager(root_dir=self.test_root_dir, yml_exists=False, yaml_exists=False)
        self.assertTrue(manager.is_service_running("my_service"))
        mock_run_command.assert_called_once_with(['docker', 'compose', 'ps', '-q', 'my_service'])

    @patch.object(DockerManager, '_run_command')
    def test_is_service_running_false_no_output(self: 'TestDockerManager', mock_run_command: MagicMock) -> None:
        """Test is_service_running returns False when command succeeds but no output."""
        mock_run_command.return_value = (True, "", "")
        manager = self._create_manager(root_dir=self.test_root_dir, yml_exists=False, yaml_exists=False)
        self.assertFalse(manager.is_service_running("my_service"))

    @patch.object(DockerManager, '_run_command')
    def test_is_service_running_false_command_fails(self: 'TestDockerManager', mock_run_command: MagicMock) -> None:
        """Test is_service_running returns False when docker command fails."""
        mock_run_command.return_value = (False, "", "Error")
        manager = self._create_manager(root_dir=self.test_root_dir, yml_exists=False, yaml_exists=False)
        self.assertFalse(manager.is_service_running("my_service"))

    @patch.object(DockerManager, '_run_command')
    def test_restart_service_success(self: 'TestDockerManager', mock_run_command: MagicMock) -> None:
        """Test restart_service successful call."""
        mock_run_command.return_value = (True, "Restarted", "")
        manager = self._create_manager(root_dir=self.test_root_dir, yml_exists=False, yaml_exists=False)
        manager.restart_service("app_service")
        mock_run_command.assert_called_once_with(['docker', 'compose', 'restart', 'app_service'])
        self.mock_logger.info.assert_any_call("Restarting service 'app_service'...")
        self.mock_logger.info.assert_any_call("Service 'app_service' restarted successfully.")

    @patch.object(DockerManager, '_run_command')
    def test_restart_service_failure(self: 'TestDockerManager', mock_run_command: MagicMock) -> None:
        """Test restart_service handles command failure."""
        mock_run_command.return_value = (False, "", "Failed to restart")
        manager = self._create_manager(root_dir=self.test_root_dir, yml_exists=False, yaml_exists=False)
        manager.restart_service("db_service")
        mock_run_command.assert_called_once_with(['docker', 'compose', 'restart', 'db_service'])
        self.mock_logger.error.assert_called_once_with("Failed to restart service 'db_service':\nFailed to restart")

    @patch.object(DockerManager, '_run_command')
    def test_get_ps_success(self: 'TestDockerManager', mock_run_command: MagicMock) -> None:
        """Test get_ps returns output on success."""
        expected_output = "NAME COMMAND STATE PORTS"
        mock_run_command.return_value = (True, expected_output, "")
        manager = self._create_manager(root_dir=self.test_root_dir, yml_exists=False, yaml_exists=False)
        self.assertEqual(manager.get_ps(), expected_output)
        mock_run_command.assert_called_once_with(['docker', 'compose', 'ps'])

    @patch.object(DockerManager, '_run_command')
    def test_get_ps_failure(self: 'TestDockerManager', mock_run_command: MagicMock) -> None:
        """Test get_ps returns None on failure."""
        mock_run_command.return_value = (False, "", "ps error")
        manager = self._create_manager(root_dir=self.test_root_dir, yml_exists=False, yaml_exists=False)
        self.assertIsNone(manager.get_ps())
        self.mock_logger.error.assert_called_once_with("Failed to get docker-compose status:\nps error")

    @patch('subprocess.Popen')
    def test_stream_logs(self: 'TestDockerManager', mock_popen: MagicMock) -> None:
        """Test stream_logs calls Popen correctly."""
        mock_process = MagicMock()
        mock_process.stdout.readline.side_effect = ["log line 1\n", "log line 2\n", ""]
        mock_process.wait.return_value = 0
        mock_popen.return_value = mock_process

        manager = self._create_manager(root_dir=self.test_root_dir, yml_exists=False, yaml_exists=False)
        manager.stream_logs("log_service")

        mock_popen.assert_called_once_with(
            ['docker', 'compose', 'logs', '-f', 'log_service'],
            stdout=unittest.mock.ANY, stderr=unittest.mock.ANY, text=True, cwd=str(self.test_root_dir)
        )
        self.mock_logger.info.assert_any_call("log line 1")
        self.mock_logger.info.assert_any_call("log line 2")

    @patch('subprocess.Popen')
    def test_run_command_in_service_success(self: 'TestDockerManager', mock_popen: MagicMock) -> None:
        """Test run_command_in_service successful execution."""
        mock_process = MagicMock()
        mock_process.stdout.readline.side_effect = ["cmd output 1\n", "cmd output 2\n", ""]
        mock_process.wait.return_value = 0
        mock_popen.return_value = mock_process

        manager = self._create_manager(root_dir=self.test_root_dir, yml_exists=False, yaml_exists=False)
        result = manager.run_command_in_service("exec_service", "ls -l /app")

        self.assertTrue(result)
        mock_popen.assert_called_once_with(
            ['docker', 'compose', 'exec', 'exec_service', 'ls', '-l', '/app'],
            stdout=unittest.mock.ANY, stderr=unittest.mock.ANY, text=True, cwd=str(self.test_root_dir)
        )
        self.mock_logger.info.assert_any_call("cmd output 1")
        self.mock_logger.info.assert_any_call("cmd output 2")

    @patch('subprocess.Popen')
    def test_run_command_in_service_failure(self: 'TestDockerManager', mock_popen: MagicMock) -> None:
        """Test run_command_in_service handles command failure inside container."""
        mock_process = MagicMock()
        mock_process.stdout.readline.side_effect = ["error output\n", ""]
        mock_process.wait.return_value = 1 # Non-zero exit code
        mock_popen.return_value = mock_process

        manager = self._create_manager(root_dir=self.test_root_dir, yml_exists=False, yaml_exists=False)
        result = manager.run_command_in_service("fail_service", "bad_command")

        self.assertFalse(result)
        self.mock_logger.error.assert_any_call("Command failed with exit code 1 in service 'fail_service'.")

    @patch('subprocess.run')
    def test_check_docker_availability_daemon_not_running(self: 'TestDockerManager', mock_run: MagicMock) -> None:
        """Test _check_docker_availability when docker daemon is not connected."""
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="Cannot connect to the Docker daemon")
        manager = self._create_manager(root_dir=None, check_docker_availability_return=False)
        self.assertFalse(manager._check_docker_availability())

    @patch('subprocess.run')
    def test_check_docker_availability_command_fails_other_reason(self: 'TestDockerManager', mock_run: MagicMock) -> None:
        """Test _check_docker_availability when docker info command fails for other reasons."""
        mock_run.return_value = MagicMock(returncode=127, stdout="", stderr="docker: command not found")
        manager = self._create_manager(root_dir=None, check_docker_availability_return=False)
        self.assertFalse(manager._check_docker_availability())

    # --- Test check_for_missing_volume_mounts ---
    def test_check_for_missing_volume_mounts_all_mounted(self: 'TestDockerManager') -> None:
        """Test check_for_missing_volume_mounts when all files are mounted."""
        compose_content = """
services:
  app:
    volumes:
      - ./src:/app/src
      - ./data:/app/data
"""
        manager = self._create_manager(root_dir=self.test_root_dir, yml_exists=True, compose_content=compose_content)
        files_in_context = [
            self.test_root_dir / "src" / "main.py",
            self.test_root_dir / "data" / "file.txt"
        ]
        manager.check_for_missing_volume_mounts(files_in_context)
        # Check that no warning was logged for missing mounts
        # This is a bit indirect; we check that specific warning messages were NOT called.
        # A more robust way might be to check call_args_list if many warnings are possible.
        for call_args in self.mock_logger.warning.call_args_list:
            args, _ = call_args
            self.assertFalse("The following files in your context are not covered by a Docker volume mount:" in args[0])


    def test_check_for_missing_volume_mounts_some_unmounted(self: 'TestDockerManager') -> None:
        """Test check_for_missing_volume_mounts warns about unmounted files."""
        compose_content = """
services:
  app:
    volumes:
      - ./src:/app/src
"""
        manager = self._create_manager(root_dir=self.test_root_dir, yml_exists=True, compose_content=compose_content)
        files_in_context = [
            self.test_root_dir / "src" / "main.py",          # Mounted
            self.test_root_dir / "config" / "settings.ini"  # Unmounted
        ]
        manager.check_for_missing_volume_mounts(files_in_context)
        self.mock_logger.warning.assert_any_call("The following files in your context are not covered by a Docker volume mount:")
        self.mock_logger.warning.assert_any_call(f"  - {Path('config/settings.ini')}")
        self.mock_logger.warning.assert_any_call("Code changes to these files will not be reflected in your running containers.")

    def test_check_for_missing_volume_mounts_no_services_or_root(self: 'TestDockerManager') -> None:
        """Test check_for_missing_volume_mounts handles no services or root_dir."""
        # Test with no services (compose file exists but is minimal)
        manager_no_services = self._create_manager(
            root_dir=self.test_root_dir, 
            yml_exists=True, 
            compose_content="version: '3.8'"
        )
        # Reset mock logger for this specific sub-test to avoid interference
        self.mock_logger.reset_mock() 
        manager_no_services.check_for_missing_volume_mounts([self.test_root_dir / "file.py"])
        self.mock_logger.warning.assert_not_called()

        # Test with no root_dir
        manager_no_root = self._create_manager(root_dir=None)
        self.mock_logger.reset_mock()
        manager_no_root.check_for_missing_volume_mounts([Path("file.py")])
        self.mock_logger.warning.assert_not_called()


if __name__ == '__main__':
    unittest.main()