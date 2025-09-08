import logging
from pathlib import Path
from typing import List, Set, Dict

from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.styles import Style

from tinycoder.ui.log_formatter import STYLES, COLORS as FmtColors, RESET
from tinycoder.ui.console_interface import prompt_user_input
from tinycoder.docker_manager import DockerManager
from tinycoder.file_manager import FileManager


class DockerAutomation:
    """Handles automated Docker service management based on file changes."""

    def __init__(self, docker_manager: DockerManager, file_manager: FileManager, logger: logging.Logger):
        """Initializes the DockerAutomation with its dependencies."""
        self.docker_manager = docker_manager
        self.file_manager = file_manager
        self.logger = logger

    def handle_modified_files(self, modified_files_rel: List[str], non_interactive: bool = False) -> None:
        """
        After edits are applied, checks for Docker context and automates actions.
        - Restarts services that don't have live-reload.
        - Prompts to build if dependency files change.
        """
        if not self.docker_manager or not self.docker_manager.is_available or not self.docker_manager.services:
            self.logger.debug("Docker automation skipped: manager not available or no services found.")
            return

        modified_files_abs = [self.file_manager.get_abs_path(f) for f in modified_files_rel if self.file_manager.get_abs_path(f)]
        if not modified_files_abs:
            return  # No valid files to check

        # find_affected_services now returns Dict[str, Set[str]]
        affected_services_map = self.docker_manager.find_affected_services(modified_files_abs)
        if not affected_services_map:
            self.logger.debug("No Docker services affected by file changes.")
            return

        services_to_build_and_restart, services_to_volume_restart_only = self._determine_service_actions(
            affected_services_map, modified_files_rel
        )

        if services_to_build_and_restart:
            self._handle_build_restart_services(services_to_build_and_restart, non_interactive)
            return  # Exit after build consideration, regardless of user choice

        # Handle services that only needed a volume-based restart (and weren't built)
        if services_to_volume_restart_only:
            self._handle_volume_restart_services(services_to_volume_restart_only, non_interactive)

    def _determine_service_actions(self, affected_services_map: Dict[str, Set[str]], modified_files_rel: List[str]) -> tuple[Set[str], Set[str]]:
        """Determine which services need build+restart vs just restart."""
        dependency_files = ["requirements.txt", "pyproject.toml", "package.json", "Pipfile", "Dockerfile"]
        modified_dep_files = any(Path(f).name.lower() in dependency_files for f in modified_files_rel)

        services_to_build_and_restart = set()
        services_to_volume_restart_only = set()

        for service_name, reasons in affected_services_map.items():
            needs_build = False

            # Check dependency files and Dockerfile changes
            if modified_dep_files:
                needs_build = self._check_service_dependency_changes(service_name, modified_files_rel)

            if "build_context" in reasons and not needs_build:
                needs_build = True
                self.logger.debug(f"Service '{service_name}' marked for build due to direct build_context change.")

            if needs_build:
                services_to_build_and_restart.add(service_name)
            elif "volume" in reasons:
                if self.docker_manager.is_service_running(service_name):
                    if not self.docker_manager.has_live_reload(service_name):
                        services_to_volume_restart_only.add(service_name)
                    else:
                        self.logger.info(
                            f"Service '{STYLES['BOLD']}{FmtColors['CYAN']}{service_name}{RESET}' affected by volume change and has live-reload, no automatic restart needed."
                        )
                else:
                    self.logger.debug(f"Service '{service_name}' affected by volume change but not running, skipping restart.")

        return services_to_build_and_restart, services_to_volume_restart_only

    def _check_service_dependency_changes(self, service_name: str, modified_files_rel: List[str]) -> bool:
        """Check if dependency files changed for a specific service."""
        service_build_config = self.docker_manager.services.get(service_name, {}).get("build", {})
        service_build_context_str = None
        if isinstance(service_build_config, str):
            service_build_context_str = service_build_config
        elif isinstance(service_build_config, dict):
            service_build_context_str = service_build_config.get("context")

        service_dockerfile_str = "Dockerfile"
        if isinstance(service_build_config, dict) and isinstance(service_build_config.get("dockerfile"), str):
            service_dockerfile_str = service_build_config.get("dockerfile")

        if service_build_context_str and self.docker_manager.root_dir:
            service_build_context_path = (self.docker_manager.root_dir / service_build_context_str).resolve()

            # Check if any modified dep file is THE Dockerfile for this service, or within its context
            for mod_file_rel in modified_files_rel:
                mod_file_abs = self.file_manager.get_abs_path(mod_file_rel)
                if not mod_file_abs:
                    continue

                # Is the modified file the Dockerfile for this service?
                dockerfile_abs_path = (service_build_context_path / service_dockerfile_str).resolve()
                if mod_file_abs == dockerfile_abs_path:
                    self.logger.debug(f"Service '{service_name}' Dockerfile '{service_dockerfile_str}' changed.")
                    return True

                # Is a generic dep file (like requirements.txt) inside this service's build context?
                if mod_file_abs.name.lower() in ["requirements.txt", "pyproject.toml", "package.json", "Pipfile", "Dockerfile"]:
                    if mod_file_abs.is_relative_to(service_build_context_path):
                        self.logger.debug(
                            f"Dependency file '{mod_file_abs.name}' changed within build context of '{service_name}'."
                        )
                        return True

        return False

    def _handle_build_restart_services(self, services_to_build_and_restart: Set[str], non_interactive: bool) -> None:
        """Handle build and restart operations for services."""
        sorted_build_services = sorted(list(services_to_build_and_restart))
        colored_services = [f"{STYLES['BOLD']}{FmtColors['YELLOW']}{s}{RESET}" for s in sorted_build_services]
        self.logger.warning(f"Services requiring build & restart: {', '.join(colored_services)}")

        if non_interactive:
            self.logger.info("Non-interactive mode: Skipping build & restart prompt. Please manage manually.")
            return

        if not self._prompt_for_build_restart(sorted_build_services):
            return

        try:
            for service in sorted_build_services:
                if self.docker_manager.build_service(service):
                    self.docker_manager.up_service_recreate(service)
        except KeyboardInterrupt:
            self.logger.info("\nBuild & restart operation cancelled by user.")

    def _handle_volume_restart_services(self, services_to_volume_restart_only: Set[str], non_interactive: bool) -> None:
        """Handle volume-based restart operations for services."""
        sorted_volume_services = sorted(list(services_to_volume_restart_only))
        colored_services = [f"{STYLES['BOLD']}{FmtColors['CYAN']}{s}{RESET}" for s in sorted_volume_services]
        self.logger.info(
            f"Services requiring restart due to volume changes (no live-reload): {', '.join(colored_services)}"
        )

        if non_interactive:
            self.logger.info("Non-interactive mode: Skipping volume-based restart. Please manage manually.")
            return

        try:
            for service in sorted_volume_services:
                self.logger.info(f"Service '{STYLES['BOLD']}{FmtColors['CYAN']}{service}{RESET}' is running without apparent live-reload and affected by volume change.")
                self.docker_manager.restart_service(service)
        except (EOFError, KeyboardInterrupt):
            self.logger.info("\nVolume restart cancelled by user.")

    def _prompt_for_build_restart(self, services_to_build: Set[str]) -> bool:
        """Prompt user for build and restart operations."""
        prompt = f"{FmtColors['YELLOW']}Rebuild and restart affected services ({', '.join(sorted(services_to_build))}) now? (y/N): {RESET}"
        confirm = prompt_user_input(prompt).strip().lower()

        if not confirm:  # User cancelled the prompt
            self.logger.info("\nBuild & restart cancelled by user.")
            return False
        return confirm == "y"