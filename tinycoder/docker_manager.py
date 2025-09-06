import logging
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Set, Any, Tuple

class DockerManager:
    """Manages Docker interactions for a project."""

    def __init__(self, root_dir: Optional[Path], logger: logging.Logger):
        """
        Initializes the DockerManager.

        Args:
            root_dir: The project root directory (e.g., git root).
            logger: The application's logger instance.
        """
        self.logger = logger
        self.root_dir: Optional[Path] = root_dir
        self.compose_file: Optional[Path] = None
        self.services: Dict[str, Any] = {}
        self.is_available = False

        if not self._check_docker_availability():
            self.logger.debug("Docker command not found or daemon not running. DockerManager disabled.")
            return
        
        self.is_available = True
        self.logger.debug("Docker is available.")
        
        if not self.root_dir:
            self.logger.debug("No project root provided. Cannot locate docker-compose.yml.")
            return

        self.compose_file = self.root_dir / 'docker-compose.yml'
        if not self.compose_file.exists():
            self.compose_file = self.root_dir / 'docker-compose.yaml' # Also check for .yaml
        
        if self.compose_file.exists():
            self.logger.debug(f"Found docker-compose file: {self.compose_file}")
            self._parse_compose_file()
        else:
            self.logger.debug("No docker-compose.yml or docker-compose.yaml found in project root.")
            self.compose_file = None # Ensure it's None if not found

    def _run_command(self, command: List[str]) -> tuple[bool, str, str]:
        """Runs a command and returns success, stdout, stderr."""
        try:
            process = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False, # We check returncode manually
                cwd=str(self.root_dir) if self.root_dir else None,
            )
            success = process.returncode == 0
            if not success:
                self.logger.debug(f"Command '{' '.join(command)}' failed with code {process.returncode}")
                self.logger.debug(f"Stderr: {process.stderr.strip()}")
            return success, process.stdout.strip(), process.stderr.strip()
        except FileNotFoundError:
            self.logger.error(f"Command not found: {command[0]}")
            return False, "", f"Command not found: {command[0]}"
        except Exception as e:
            self.logger.error(f"Error running command '{' '.join(command)}': {e}")
            return False, "", str(e)

    def _check_docker_availability(self) -> bool:
        """
        Checks if the Docker command is available and the daemon is running.
        Handles FileNotFoundError gracefully for when docker is not installed.
        """
        try:
            process = subprocess.run(
                ['docker', 'info'],
                capture_output=True,
                text=True,
                check=False,
                cwd=str(self.root_dir) if self.root_dir else None,
            )
            # This error means the daemon is not running.
            if "Cannot connect to the Docker daemon" in process.stderr:
                return False
            # Any other non-zero return code is also a failure.
            return process.returncode == 0
        except FileNotFoundError:
            # This means the 'docker' command itself was not found.
            return False
        except Exception as e:
            # Log other unexpected errors at debug level.
            self.logger.debug(f"An unexpected error occurred while checking for Docker: {e}")
            return False

    def _parse_compose_file(self):
        """Parses the docker-compose.yml file using a pure Python parser."""
        if not self.compose_file:
            return

        try:
            with open(self.compose_file, 'r', encoding='utf-8') as f:
                content = f.read()

            compose_data = self._parse_yaml_simple(content)

            if compose_data and 'services' in compose_data and isinstance(compose_data.get('services'), dict):
                self.services = compose_data['services']
                self.logger.debug(f"Parsed services from compose file: {', '.join(self.services.keys())}")
            elif compose_data:
                self.logger.warning("docker-compose.yml seems to be invalid or has no 'services' dictionary.")
            # else: self._parse_yaml_simple would have logged any errors

        except IOError as e:
            self.logger.error(f"Error reading {self.compose_file}: {e}")
        except Exception as e:
            self.logger.error(f"An unexpected error occurred while parsing {self.compose_file}: {e}")

    def _parse_yaml_simple(self, content: str) -> Optional[Dict[str, Any]]:
        """
        A lightweight, pure-Python YAML parser for docker-compose files.
        This parser is designed to handle indentation-based key-value pairs and lists
        of strings, which covers the majority of docker-compose.yml syntax. It does not
        support advanced features like anchors, aliases, or multi-line strings.
        """
        lines_with_indent = []
        for line in content.splitlines():
            # Strip comments and trailing whitespace
            sanitized = line.split('#', 1)[0].rstrip()
            if not sanitized:
                continue
            indent = len(line) - len(line.lstrip(' '))
            lines_with_indent.append((indent, sanitized.strip()))

        if not lines_with_indent:
            return None

        # We use a recursive helper function to build the structure.
        data, _ = self._build_node(lines_with_indent, 0, -1)
        return data

    def _build_node(self, lines: List[Tuple[int, str]], start_index: int, parent_indent: int) -> Tuple[Any, int]:
        """Recursively builds a dictionary or list node from a list of indented lines."""
        if start_index >= len(lines):
            return None, start_index

        first_indent, first_line = lines[start_index]

        # This block of lines is not a child of the caller, so return control.
        if first_indent <= parent_indent:
            return None, start_index

        # Decide if this node is a dictionary or a list based on the first line.
        if first_line.startswith('- '):
            # It's a list
            node = []
            current_index = start_index
            while current_index < len(lines):
                indent, line = lines[current_index]
                if indent < first_indent:
                    break  # End of list block (de-dented)

                if indent > first_indent:
                    self.logger.warning(f"YAML parser: Unexpected indent in list, skipping line: '{line}'")
                    current_index += 1
                    continue

                if not line.startswith('- '):
                    break  # End of list block (different item type)

                value = line[2:].strip()
                node.append(value)
                current_index += 1
            return node, current_index
        else:
            # It's a dictionary
            node = {}
            current_index = start_index
            while current_index < len(lines):
                indent, line = lines[current_index]
                if indent < first_indent:
                    break  # End of dict block (de-dented)

                if indent > first_indent:
                    # This line is a child of a previous key, but we handle that via recursion.
                    # If we are in this loop, we only process lines at the *same* level.
                    # So we skip this mis-indented line.
                    current_index += 1
                    continue

                if ':' not in line:
                    break  # End of dict block (not a key:value pair)

                key, value_str_raw = line.split(':', 1)
                key = key.strip()
                value_str = value_str_raw.strip() # Stripped value for logic checks

                # Attempt to parse children first.
                # A child node starts at current_index + 1 and must be more indented than parent_indent (first_indent here).
                child_node, next_index_after_child = self._build_node(lines, current_index + 1, first_indent)

                if child_node is not None:
                    node[key] = child_node
                    current_index = next_index_after_child
                elif value_str_raw: # If there was anything after ':', even just whitespace (now stripped to value_str)
                                    # This covers "key: value" and "key: " (value_str is empty) and "key:" (value_str is empty)
                                    # The critical part is that value_str_raw was not empty, meaning ':' was not at line end.
                                    # If value_str_raw.strip() is non-empty, use it. Otherwise, if value_str_raw existed (e.g. "key: "), use ""
                    node[key] = value_str # Assign the stripped value, which could be ""
                    current_index += 1
                else: # No child node, and value_str_raw was empty (e.g. "key:" at end of line, or "key:\n")
                      # This implies ':' was the last non-whitespace char or line ended after ':'.
                    node[key] = None # Standard representation for an empty YAML value
                    current_index += 1
            return node, current_index

    def find_affected_services(self, modified_files: List[Path]) -> Dict[str, Set[str]]:
        """
        Identifies which services are affected by file changes based on 
        volume mounts or build contexts.

        Args:
            modified_files: A list of absolute paths to modified files.

        Returns:
            A dictionary mapping service names to a set of reasons 
            (e.g., {"volume", "build_context"}).
        """
        affected_map: Dict[str, Set[str]] = {}
        if not self.services or not self.root_dir:
            return affected_map

        for service_name, service_def in self.services.items():
            reasons_for_affect: Set[str] = set()

            # Check 1: Volume mounts
            volumes = service_def.get('volumes', [])
            if isinstance(volumes, list): # Ensure volumes is a list
                for volume_entry in volumes:
                    if isinstance(volume_entry, str) and ':' in volume_entry:
                        host_path_str = volume_entry.split(':')[0]
                        # Resolve host path relative to the compose file's directory (root_dir)
                        host_path = (self.root_dir / host_path_str).resolve()
                        for modified_file in modified_files:
                            # Ensure modified_file is absolute before comparison
                            if modified_file.resolve().is_relative_to(host_path):
                                reasons_for_affect.add("volume")
                                break # Found a volume match for this service, check next modified_file
                    if "volume" in reasons_for_affect: # If one volume matched, no need to check other volumes for this service
                        break 
            
            # Check 2: Build context
            build_config = service_def.get('build')
            build_context_str: Optional[str] = None

            if isinstance(build_config, str):
                build_context_str = build_config
            elif isinstance(build_config, dict):
                ctx = build_config.get('context')
                if isinstance(ctx, str):
                    build_context_str = ctx
            
            if build_context_str:
                # build_context_str is relative to the docker-compose.yml file (self.root_dir)
                build_context_path = (self.root_dir / build_context_str).resolve()
                for modified_file in modified_files:
                    if modified_file.resolve().is_relative_to(build_context_path):
                        reasons_for_affect.add("build_context")
                        self.logger.debug(
                            f"Service '{service_name}' affected due to change in build context: "
                            f"{modified_file.relative_to(self.root_dir if self.root_dir else Path.cwd())}"
                        )
                        break # Found a build_context match, check next service
            
            if reasons_for_affect:
                affected_map[service_name] = reasons_for_affect
        
        if affected_map:
            self.logger.debug(f"Affected services map: {affected_map}")
        return affected_map
    
    def has_live_reload(self, service_name: str) -> bool:
        """
        Uses heuristics to check if a service is configured for live reloading.
        """
        service_def = self.services.get(service_name, {})
        command = service_def.get('command', '')
        if not isinstance(command, str): # Command can be a list
            command = ' '.join(command)

        # Common live-reload flags/tools
        live_reload_indicators = [
            '--reload',           # uvicorn
            'FLASK_ENV=development', # flask
            'nodemon',            # node.js
            'watchmedo',          # watchdog
            '--watch'             # various tools
        ]
        
        # Check environment variables as well
        environment = service_def.get('environment', [])
        env_str = ' '.join(environment) if isinstance(environment, list) else ' '.join(f'{k}={v}' for k, v in (environment or {}).items())

        if any(indicator in command for indicator in live_reload_indicators) or \
           any(indicator in env_str for indicator in live_reload_indicators):
            self.logger.debug(f"Service '{service_name}' appears to have live reload configured.")
            return True
        
        self.logger.debug(f"Service '{service_name}' does not appear to have live reload configured.")
        return False

    def is_service_running(self, service_name: str) -> bool:
        """Checks if a specific service is running."""
        success, stdout, _ = self._run_command(['docker', 'compose', 'ps', '-q', service_name])
        return success and bool(stdout)

    def restart_service(self, service_name: str):
        """Restarts a specific docker-compose service."""
        self.logger.info(f"Restarting service '{service_name}'...")
        success, _, stderr = self._run_command(['docker', 'compose', 'restart', service_name])
        if not success:
            self.logger.error(f"Failed to restart service '{service_name}':\n{stderr}")
        else:
            self.logger.info(f"Service '{service_name}' restarted successfully.")

    def up_service_recreate(self, service_name: str) -> bool:
        """
        Brings up a service, forcing recreation of its containers, using the latest image.
        Assumes the image has already been built if necessary.
        """
        self.logger.info(f"Recreating service '{service_name}' with the latest image...")
        # --no-build: Assumes build was handled separately
        # --force-recreate: Ensures old container is replaced
        # -d: Detached mode
        command = ['docker', 'compose', 'up', '-d', '--force-recreate', '--no-build', service_name]
        success, stdout, stderr = self._run_command(command)
        if not success:
            self.logger.error(f"Failed to recreate service '{service_name}':\n{stderr}")
            if stdout: # Sometimes error details are in stdout for 'up'
                self.logger.error(f"Stdout:\n{stdout}")
            return False
        else:
            self.logger.info(f"Service '{service_name}' recreated and started successfully.")
            if stdout: # Log stdout for 'up' even on success as it can be informative
                self.logger.debug(f"Output from 'docker compose up':\n{stdout}")
            return True

    def build_service(self, service_name: str, non_interactive=False) -> bool:
        """Builds a specific docker-compose service, utilizing Docker's build cache."""
        self.logger.info(f"Building service '{service_name}' (using cache)...")
        # Removed --no-cache to allow Docker to use its build cache.
        # Docker's cache invalidation (e.g., for changed COPYed files) will trigger rebuilds as needed.
        success, stdout, stderr = self._run_command(['docker', 'compose', 'build', service_name])
        if not success:
            self.logger.error(f"Failed to build service '{service_name}':\n{stderr}")
            if stdout: # Build errors can sometimes appear in stdout
                self.logger.error(f"Stdout:\n{stdout}")
            return False
        else:
            self.logger.info(f"Service '{service_name}' built successfully.")
            if stdout: # Log stdout for 'build' as well, can be informative
                self.logger.debug(f"Output from 'docker compose build':\n{stdout}")
            return True

    def get_ps(self) -> Optional[str]:
        """Runs 'docker-compose ps' and returns the output."""
        success, stdout, stderr = self._run_command(['docker', 'compose', 'ps'])
        if not success:
            self.logger.error(f"Failed to get docker-compose status:\n{stderr}")
            return None
        return stdout

    def stream_logs(self, service_name: str):
        """Streams logs from a specific docker-compose service."""
        self.logger.info(f"Streaming logs for service '{service_name}'. Press Ctrl+C to stop.")
        try:
            # Using Popen for live output streaming
            process = subprocess.Popen(
                ['docker', 'compose', 'logs', '-f', service_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=str(self.root_dir) if self.root_dir else None
            )
            if process.stdout:
                for line in iter(process.stdout.readline, ''):
                    self.logger.info(line.strip())
            process.wait()
        except KeyboardInterrupt:
            self.logger.info(f"\nStopped streaming logs for '{service_name}'.")
        except Exception as e:
            self.logger.error(f"Error streaming logs for '{service_name}': {e}")

    def run_command_in_service(self, service_name: str, command: str) -> bool:
        """Runs a command inside a specified service container."""
        self.logger.info(f"Running command in service '{service_name}': {command}")
        
        # We need to use Popen to stream the output nicely
        try:
            full_command = ['docker', 'compose', 'exec', service_name] + command.split()
            process = subprocess.Popen(
                full_command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=str(self.root_dir) if self.root_dir else None
            )
            if process.stdout:
                for line in iter(process.stdout.readline, ''):
                    self.logger.info(line.strip())
            
            retcode = process.wait()
            if retcode != 0:
                self.logger.error(f"Command failed with exit code {retcode} in service '{service_name}'.")
                return False
            return True
        except Exception as e:
            self.logger.error(f"Failed to execute command in service '{service_name}': {e}")
            return False

    def check_for_missing_volume_mounts(self, files_in_context: List[Path]):
        """Checks if files in context are covered by a volume mount and warns if not."""
        if not self.services or not self.root_dir or not files_in_context:
            return

        unmounted_files = []
        for file_path in files_in_context:
            is_mounted = False
            for service_def in self.services.values():
                volumes = service_def.get('volumes', [])
                for volume in volumes:
                    if isinstance(volume, str) and ':' in volume:
                        host_path_str = volume.split(':')[0]
                        host_path = (self.root_dir / host_path_str).resolve()
                        if file_path.resolve().is_relative_to(host_path):
                            is_mounted = True
                            break
                if is_mounted:
                    break
            if not is_mounted:
                unmounted_files.append(file_path)
        
        if unmounted_files:
            relative_paths = [f.relative_to(self.root_dir) for f in unmounted_files]
            self.logger.warning("The following files in your context are not covered by a Docker volume mount:")
            for rel_path in relative_paths:
                # The logger's formatter will handle coloring based on the 'warning' level
                self.logger.warning(f"  - {rel_path}")
            self.logger.warning("Code changes to these files will not be reflected in your running containers.")