import importlib.resources
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Set

# Constant for the built-in rules package
BUILTIN_RULES_PACKAGE = "tinycoder.rules"


class RuleManager:
    """Manages discovery, loading, and configuration of rules."""

    def __init__(
        self,
        project_identifier: str,
        rules_config_path: Path,
        base_dir: Path,  # This would be git_root or cwd
        logger: logging.Logger,
    ):
        """
        Initializes the RuleManager.

        Args:
            project_identifier: A unique string identifying the project (e.g., git root path).
            rules_config_path: Path to the rules_config.json file.
            base_dir: The base directory for resolving custom rules (usually project root or cwd).
            logger: The logger instance for logging messages.
        """
        self.project_identifier = project_identifier
        self.rules_config_path = rules_config_path
        self.base_dir = base_dir  # Used for finding custom rules relative paths
        self.logger = logger

        self.discovered_rules: Dict[str, Dict[str, Any]] = {}
        self.active_rules_content: str = ""
        self.last_loaded_rule_names: Set[str] = set() # Stores names of successfully loaded rules

        self._discover_rules()
        self.load_active_rules_content()  # Load initially

    def _load_rules_config(self) -> Dict[str, Any]:
        """Loads the global rules configuration from the JSON file."""
        if not self.rules_config_path.exists():
            return {}
        try:
            with open(self.rules_config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
                if not isinstance(config, dict):
                    self.logger.error(
                        f"Invalid format in {self.rules_config_path}. "
                        "Expected a JSON object. Ignoring config."
                    )
                    return {}
                return config
        except json.JSONDecodeError:
            self.logger.error(
                f"Error decoding JSON from {self.rules_config_path}. Ignoring config."
            )
            return {}
        except Exception as e:
            self.logger.error(
                f"Failed to read rules config {self.rules_config_path}: {e}"
            )
            return {}

    def _save_rules_config(self, config: Dict[str, Any]) -> None:
        """Saves the global rules configuration to the JSON file."""
        try:
            self.rules_config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.rules_config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)
        except Exception as e:
            self.logger.error(
                f"Failed to save rules config to {self.rules_config_path}: {e}"
            )

    def _discover_rules(self) -> None:
        """Discovers built-in and custom rules."""
        self.discovered_rules = {}
        num_built_in = 0
        num_custom = 0

        # 1. Discover Built-in Rules
        try:
            if sys.version_info >= (3, 9):
                resource_files = importlib.resources.files(BUILTIN_RULES_PACKAGE)
                for item in resource_files.iterdir():
                    if item.is_file() and item.name.endswith(".md") and item.name != "__init__.py":
                        rule_name = item.stem
                        title = rule_name.replace("_", " ").title()
                        self.discovered_rules[rule_name] = {
                            "type": "builtin",
                            "path": item.name,  # Store resource name relative to package
                            "title": title,
                        }
                        num_built_in += 1
            else:  # Fallback for Python < 3.9
                 # This assumes tinycoder.rules is a package (has __init__.py)
                 import tinycoder.rules as rules_module
                 if hasattr(rules_module, '__path__'):
                     pkg_path = Path(rules_module.__path__[0])
                     for rule_file in pkg_path.glob("*.md"):
                         if rule_file.is_file() and rule_file.name != "__init__.py":
                            rule_name = rule_file.stem
                            title = rule_name.replace("_", " ").title()
                            self.discovered_rules[rule_name] = {
                                "type": "builtin",
                                "path": rule_file.name, # Store filename relative to package dir
                                "title": title,
                             }
                            num_built_in += 1
        except (ModuleNotFoundError, FileNotFoundError, Exception) as e:
            self.logger.warning(f"Could not discover built-in rules: {e}")

        # 2. Discover Custom Rules
        # self.base_dir is git_root (if available) or cwd.
        custom_rules_dir = self.base_dir / ".tinycoder" / "rules"
        if custom_rules_dir.is_dir():
            for rule_file in custom_rules_dir.glob("*.md"):
                if rule_file.is_file():
                    rule_name = rule_file.stem
                    title = rule_name.replace("_", " ").title()
                    if rule_name in self.discovered_rules and self.discovered_rules[rule_name]['type'] == 'builtin':
                       self.logger.info(f"Custom rule '{rule_name}' overrides built-in rule.")
                       num_built_in -= 1
                    self.discovered_rules[rule_name] = {
                        "type": "custom",
                        "path": rule_file.resolve(), # Store absolute Path for custom rules
                        "title": title,
                    }
                    num_custom += 1
        self.logger.debug(f"Discovered {num_built_in} built-in rule(s) and {num_custom} custom rule(s).")

    def _get_enabled_rules_for_project(self) -> Set[str]:
        """Gets the set of enabled rule names for the current project from the config."""
        config = self._load_rules_config()
        project_config = config.get(self.project_identifier, {})
        enabled_rules = project_config.get("enabled_rules", [])
        if not isinstance(enabled_rules, list):
            self.logger.warning(
                f"Invalid 'enabled_rules' format for project {self.project_identifier} "
                f"in config. Expected a list, found {type(enabled_rules)}. Using empty list."
            )
            return set()
        return set(enabled_rules)

    def load_active_rules_content(self) -> str:
        """
        Loads content of enabled rules (built-in and custom) for the current project.
        Updates self.active_rules_content and returns it.
        """
        enabled_rule_names = self._get_enabled_rules_for_project()
        active_rules_content_parts = []
        loaded_rule_names = set() # Track loaded to ensure precedence

        # Load custom rules first to ensure they have precedence
        for rule_name, rule_info in self.discovered_rules.items():
             if rule_name in enabled_rule_names and rule_info["type"] == "custom":
                try:
                    # rule_info["path"] is already a resolved Path for custom rules
                    content = rule_info["path"].read_text(encoding="utf-8")
                    active_rules_content_parts.append(
                        f"### Rule: {rule_info['title']}\n\n{content.strip()}\n"
                    )
                    loaded_rule_names.add(rule_name)
                except Exception as e:
                     self.logger.error(f"Failed to read custom rule file {rule_info['path']}: {e}")

        # Load enabled built-in rules only if not already loaded as custom
        for rule_name, rule_info in self.discovered_rules.items():
            if rule_name in enabled_rule_names and rule_info["type"] == "builtin" and rule_name not in loaded_rule_names:
                try:
                    resource_name = str(rule_info['path']) # path is filename relative to package
                    content = importlib.resources.read_text(BUILTIN_RULES_PACKAGE, resource_name, encoding="utf-8")
                    active_rules_content_parts.append(
                        f"### Rule: {rule_info['title']}\n\n{content.strip()}\n"
                    )
                    loaded_rule_names.add(rule_name)
                except Exception as e:
                    self.logger.error(f"Failed to read built-in rule resource {BUILTIN_RULES_PACKAGE}/{rule_info['path']}: {e}")

        self.active_rules_content = "\n".join(active_rules_content_parts)
        self.last_loaded_rule_names = loaded_rule_names # Store the set of loaded rule names
        
        if loaded_rule_names:
             self.logger.debug(f"Loaded {len(loaded_rule_names)} active rule(s) for this project: {', '.join(sorted(loaded_rule_names))}")
        else:
             self.logger.debug("No active rules enabled or loaded for this project.")
        return self.active_rules_content

    def get_active_rules_content(self) -> str:
        """Returns the currently loaded active rules content."""
        return self.active_rules_content

    def get_rule_content(self, rule_name: str) -> Optional[str]:
        """Reads the content of a specific discovered rule (built-in or custom)."""
        if rule_name not in self.discovered_rules:
            self.logger.error(f"Attempted to get content for unknown rule: {rule_name}")
            return None

        rule_info = self.discovered_rules[rule_name]
        try:
            if rule_info["type"] == "custom":
                # rule_info["path"] is an absolute Path object for custom rules
                return rule_info["path"].read_text(encoding="utf-8")
            elif rule_info["type"] == "builtin":
                # rule_info["path"] is a resource name (filename) for built-in rules
                resource_name = str(rule_info['path'])
                return importlib.resources.read_text(BUILTIN_RULES_PACKAGE, resource_name, encoding="utf-8")
            else:
                self.logger.error(f"Unknown rule type '{rule_info['type']}' for rule '{rule_name}'")
                return None
        except Exception as e:
            self.logger.error(f"Failed to read content for rule '{rule_name}': {e}")
            return None

    def list_rules(self) -> str:
        """
        Returns a formatted string listing discovered rules and their status,
        separated by type, sorted alphabetically, and including token estimates.
        """
        if not self.discovered_rules:
            return "No rules (built-in or custom) discovered."

        enabled_rules = self._get_enabled_rules_for_project()
        builtin_lines = []
        custom_lines = []
        sorted_rule_names = sorted(self.discovered_rules.keys())

        for rule_name in sorted_rule_names:
            rule_info = self.discovered_rules[rule_name]
            status_marker = "[✓]" if rule_name in enabled_rules else "[ ]"
            content = self.get_rule_content(rule_name)
            token_estimate = len(content) // 4 if content else 0 # Simple token estimation
            token_str = f" (~{token_estimate} tokens)"

            if rule_info['type'] == 'builtin':
                builtin_lines.append(f" {status_marker} {rule_name}{token_str}")
            elif rule_info['type'] == 'custom':
                try:
                    # rule_info['path'] is an absolute Path for custom rules
                    # self.base_dir is the project root or cwd
                    rel_path = rule_info['path'].relative_to(self.base_dir)
                    origin = f"(./{rel_path})"
                except ValueError: # If path is not relative to base_dir (e.g. different drive on Windows)
                    origin = f"({rule_info['path']})"
                custom_lines.append(f" {status_marker} {rule_name}{token_str} {origin}")
            else:
                 self.logger.warning(f"Skipping rule '{rule_name}' with unknown type '{rule_info['type']}'.")

        output_lines = []
        if builtin_lines:
            output_lines.append("--- Built-in Rules ---")
            output_lines.extend(builtin_lines)
        if custom_lines:
            if output_lines: # Add separator if built-in rules were listed
                 output_lines.append("")
            output_lines.append("--- Custom Rules ---")
            output_lines.extend(custom_lines)

        if not output_lines: # Case where discovery finds something but it's an unknown type
            return "No valid built-in or custom rules discovered to list."
        return "\n".join(output_lines)

    def enable_rule(self, rule_name: str) -> bool:
        """Enables a rule for the current project and reloads active rules."""
        if rule_name not in self.discovered_rules:
            self.logger.error(f"Rule '{rule_name}' not found.")
            return False

        config = self._load_rules_config()
        project_config = config.setdefault(self.project_identifier, {"enabled_rules": []})
        if not isinstance(project_config.get("enabled_rules"), list): # Ensure it's a list
            project_config["enabled_rules"] = []

        if rule_name not in project_config["enabled_rules"]:
            project_config["enabled_rules"].append(rule_name)
            self._save_rules_config(config)
            self.load_active_rules_content() # Reload active rules
            self.logger.info(f"Rule '{rule_name}' enabled for this project.")
        else:
            self.logger.info(f"Rule '{rule_name}' is already enabled.")
        return True

    def disable_rule(self, rule_name: str) -> bool:
        """Disables a rule for the current project and reloads active rules."""
        if rule_name not in self.discovered_rules:
            self.logger.warning(f"Rule '{rule_name}' not found, cannot disable.")
            return False

        config = self._load_rules_config()
        project_config = config.get(self.project_identifier)
        if not project_config or "enabled_rules" not in project_config or rule_name not in project_config["enabled_rules"]:
            self.logger.info(f"Rule '{rule_name}' is not currently enabled, nothing to disable.")
            return True # Indicate success as the rule is effectively disabled

        try:
            project_config["enabled_rules"].remove(rule_name)
            self._save_rules_config(config)
            self.load_active_rules_content() # Reload active rules
            self.logger.info(f"Rule '{rule_name}' disabled for this project.")
            return True
        except ValueError: # Should not happen with the 'in' check, but defensive
            self.logger.info(f"Rule '{rule_name}' was not found in the enabled list (concurrent modification?).")
            return True # Still effectively disabled
        except Exception as e:
            self.logger.error(f"Error disabling rule '{rule_name}': {e}")
            return False