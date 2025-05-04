import ast
import os
from collections import defaultdict


def infer_module_name(file_path):
    """Infer the module name based on directory structure."""
    abs_path = os.path.abspath(file_path)
    directory = os.path.dirname(abs_path)

    # Check if there's a setup.py or pyproject.toml in any parent directory
    potential_module_dirs = []
    current_dir = directory

    while current_dir and current_dir != os.path.dirname(current_dir):
        if os.path.exists(os.path.join(current_dir, "setup.py")) or os.path.exists(
            os.path.join(current_dir, "pyproject.toml")
        ):
            potential_module_dirs.append(current_dir)
        current_dir = os.path.dirname(current_dir)

    if not potential_module_dirs:
        # If no setup.py/pyproject.toml found, use the parent directory name
        return os.path.basename(directory)

    # Use the closest directory with setup.py/pyproject.toml
    module_root = potential_module_dirs[0]

    # Get the first directory under the module root, which is likely the module name
    rel_path = os.path.relpath(directory, module_root)
    if rel_path == ".":
        # We're directly in the module root, use the directory name
        return os.path.basename(module_root)
    else:
        # Return the first part of the relative path
        return rel_path.split(os.path.sep)[0]


def find_local_modules(directory):
    """Find all potential local Python modules in the given directory and subdirectories."""
    local_modules = set()
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith(".py"):
                # Get module name from file path
                rel_path = os.path.relpath(os.path.join(root, file), directory)
                module_path = os.path.splitext(rel_path)[0].replace(os.path.sep, ".")
                # Add the module and all its parent packages
                parts = module_path.split(".")
                for i in range(1, len(parts) + 1):
                    local_modules.add(".".join(parts[:i]))
    return local_modules


def is_submodule_of_any(module_name, local_modules):
    """Check if a module is a submodule of any local module."""
    parts = module_name.split(".")
    # Check if the first part of the import is in our local modules
    return parts[0] in local_modules


def resolve_import_path(import_name, file_path, module_level=0):
    """Resolve the actual file path for an import."""
    current_dir = os.path.dirname(os.path.abspath(file_path))

    # Handle relative imports
    if module_level > 0:
        for _ in range(module_level):
            current_dir = os.path.dirname(current_dir)

    # Convert import name to path
    import_parts = import_name.split(".")
    import_path = os.path.join(current_dir, *import_parts) + ".py"

    # Check if direct file exists
    if os.path.exists(import_path):
        return import_path

    # Check if it's a directory with __init__.py
    init_path = os.path.join(os.path.dirname(import_path), "__init__.py")
    if os.path.exists(init_path):
        return init_path

    # Try project root
    project_root = find_project_root(file_path)
    if project_root:
        import_path = os.path.join(project_root, *import_parts) + ".py"
        if os.path.exists(import_path):
            return import_path

        # Check for __init__.py
        init_path = os.path.join(os.path.dirname(import_path), "__init__.py")
        if os.path.exists(init_path):
            return init_path

    return None


def find_project_root(file_path):
    """Find the project root by looking for setup.py or pyproject.toml."""
    current_dir = os.path.dirname(os.path.abspath(file_path))

    while current_dir and current_dir != os.path.dirname(current_dir):
        if os.path.exists(os.path.join(current_dir, "setup.py")) or os.path.exists(
            os.path.join(current_dir, "pyproject.toml")
        ):
            return current_dir
        current_dir = os.path.dirname(current_dir)

    return None


def extract_classes_and_functions(file_path):
    """Extract all class and function names from a file."""
    try:
        with open(file_path, "r") as f:
            tree = ast.parse(f.read())

        classes = []
        functions = []

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                classes.append(node.name)
            elif isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
                functions.append(node.name)

        return classes, functions
    except Exception as e:
        print(f"Error parsing {file_path}: {e}")
        return [], []


def find_local_imports_with_entities(file_path, project_root=None):
    """
    Find all local imports in the given file and their exported entities.
    Paths are made relative to the provided project_root, or os.getcwd() if None.
    """
    # Get the directory containing the file
    directory = os.path.dirname(os.path.abspath(file_path))
    base_path = project_root if project_root else os.getcwd()

    # Infer the module name
    module_name = infer_module_name(file_path)

    # Find all local modules
    local_modules = find_local_modules(directory)
    local_modules.add(module_name)

    # Parse the file
    with open(file_path, "r") as f:
        tree = ast.parse(f.read(), file_path)

    # Store import info by path
    imports_by_path = defaultdict(set)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for name in node.names:
                if is_submodule_of_any(name.name, local_modules):
                    # Resolve the actual path
                    import_path = resolve_import_path(name.name, file_path)
                    if import_path:
                        rel_path = os.path.relpath(import_path, base_path)
                        # If we're importing the whole module, extract all classes/functions
                        classes, functions = extract_classes_and_functions(import_path)
                        for cls in classes:
                            imports_by_path[rel_path].add(f'"{cls}"')
                        for func in functions:
                            imports_by_path[rel_path].add(f'"{func}"')

        elif isinstance(node, ast.ImportFrom):
            if node.level > 0 or (
                node.module and is_submodule_of_any(node.module, local_modules)
            ):
                # Resolve the import path
                import_path = resolve_import_path(
                    node.module or "", file_path, node.level
                )
                if import_path:
                    rel_path = os.path.relpath(import_path, base_path)
                    # Add specific imported names
                    for alias in node.names:
                        if alias.name == "*":
                            # Import all names
                            classes, functions = extract_classes_and_functions(
                                import_path
                            )
                            for cls in classes:
                                imports_by_path[rel_path].add(f"{cls}")
                            for func in functions:
                                imports_by_path[rel_path].add(f"{func}")
                        else:
                            imports_by_path[rel_path].add(f"{alias.name}")

    # Format the result
    result = []
    for path, entities in imports_by_path.items():
        if entities:
            entities_str = ", ".join(sorted(entities))
            result.append(f"`{entities_str}` from `{path}`")

    return result


# Example usage
if __name__ == "__main__":
    file_to_check = "tinycoder/__init__.py"
    import_statements = find_local_imports_with_entities(file_to_check)
    for statement in import_statements:
        print(statement)
