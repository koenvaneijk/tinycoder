All changes to files must use this *SEARCH/REPLACE block* format.
ONLY EVER RETURN CODE IN A *SEARCH/REPLACE BLOCK*!

# *SEARCH/REPLACE block* Rules:

Every *SEARCH/REPLACE block* must use this format:

The *FULL* file path alone on a line
```python
<<<<<<< SEARCH
A contiguous chunk of lines to search for in the existing source code
=======
The lines to replace into the source code
>>>>>>> REPLACE
```

Example:

mathweb/flask/app.py
<<<<<<< SEARCH
from flask import Flask
=======
import math
from flask import Flask
>>>>>>> REPLACE

Every *SEARCH* section must *EXACTLY MATCH* the existing file content.
Include enough lines in each SEARCH section to uniquely match the code that needs to change.

If you want to put code in a new file, use a *SEARCH/REPLACE block* with:
- A new file path
- An empty `SEARCH` section
- The new file's contents in the `REPLACE` section

To move code within a file, use 2 *SEARCH/REPLACE* blocks: 1 to delete it, 1 to insert it.