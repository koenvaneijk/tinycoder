import logging
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Set, Any

# Try to import yaml, but don't make it a hard requirement for the whole app
try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False

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
        """Checks if the Docker daemon is running."""
        success, _, stderr = self._run_command(['docker', 'info'])
        if "Cannot connect to the Docker daemon" in stderr:
            return False
        return success

    def _parse_compose_file(self):
        """Parses the docker-compose.yml file to extract service information."""
        if not YAML_AVAILABLE:
            self.logger.warning("PyYAML is not installed. Cannot parse docker-compose.yml. Run 'pip install PyYAML'.")
            return
        
        if not self.compose_file:
            return

        try:
            with open(self.compose_file, 'r') as f:
                compose_data = yaml.safe_load(f)
            
            if compose_data and 'services' in compose_data:
                self.services = compose_data['services']
                self.logger.debug(f"Parsed services from compose file: {', '.join(self.services.keys())}")
            else:
                self.logger.warning("docker-compose.yml seems to be invalid or has no services defined.")
        except yaml.YAMLError as e:
            self.logger.error(f"Error parsing {self.compose_file}: {e}")
        except IOError as e:
            self.logger.error(f"Error reading {self.compose_file}: {e}")

    def find_affected_services(self, modified_files: List[Path]) -> Set[str]:
        """
        Identifies which services are affected by file changes based on volume mounts.

        Args:
            modified_files: A list of absolute paths to modified files.

        Returns:
            A set of service names affected by the changes.
        """
        affected = set()
        if not self.services or not self.root_dir:
            return affected

        for service_name, service_def in self.services.items():
            volumes = service_def.get('volumes', [])
            for volume in volumes:
                if isinstance(volume, str) and ':' in volume:
                    host_path_str = volume.split(':')[0]
                    # Resolve host path relative to the compose file's directory (root_dir)
                    host_path = (self.root_dir / host_path_str).resolve()
                    
                    for modified_file in modified_files:
                        # Ensure modified_file is absolute before comparison
                        if modified_file.resolve().is_relative_to(host_path):
                            affected.add(service_name)
                            break # Move to next service once one match is found
        
        if affected:
            self.logger.debug(f"Affected services identified: {', '.join(affected)}")
        return affected
    
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
        success, stdout, _ = self._run_command(['docker-compose', 'ps', '-q', service_name])
        return success and bool(stdout)

    def restart_service(self, service_name: str):
        """Restarts a specific docker-compose service."""
        self.logger.info(f"Restarting service '{service_name}'...")
        success, _, stderr = self._run_command(['docker-compose', 'restart', service_name])
        if not success:
            self.logger.error(f"Failed to restart service '{service_name}':\n{stderr}")
        else:
            self.logger.info(f"Service '{service_name}' restarted successfully.")

    def build_service(self, service_name: str, non_interactive=False) -> bool:
        """Builds a specific docker-compose service."""
        self.logger.info(f"Building service '{service_name}'...")
        success, stdout, stderr = self._run_command(['docker-compose', 'build', service_name])
        if not success:
            self.logger.error(f"Failed to build service '{service_name}':\n{stderr}")
            return False
        else:
            self.logger.info(f"Service '{service_name}' built successfully.")
            return True

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
                self.logger.warning(f"  - {FmtColors['YELLOW']}{rel_path}{RESET}")
            self.logger.warning("Code changes to these files will not be reflected in your running containers.")