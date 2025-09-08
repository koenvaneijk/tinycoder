import unittest
from unittest.mock import patch
import logging
from io import StringIO

from tinycoder.edit_parser import EditParser


class TestEditParser(unittest.TestCase):
    """Unit tests for the EditParser class."""

    def setUp(self):
        """Set up test fixtures."""
        self.parser = EditParser()
        # Capture log output for testing warnings
        self.log_stream = StringIO()
        handler = logging.StreamHandler(self.log_stream)
        self.parser.logger.addHandler(handler)
        self.parser.logger.setLevel(logging.WARNING)

    def tearDown(self):
        """Clean up after tests."""
        self.parser.logger.handlers.clear()

    def test_parse_basic_valid_edits(self):
        """Test parsing of basic valid edit blocks."""
        response = """
Some introductory text.
<edit path="./path/to/file1.py">
<find>
print("hello old world")</find>
<replace>
print("hello new world")</replace>
</edit>
Some text in between.
<edit path="another/file.txt">
<find>old line1
old line2</find>
<replace>new line1
new line2
new line3</replace>
</edit>
        """
        
        result = self.parser.parse(response)
        
        self.assertEqual(len(result["edits"]), 2)
        self.assertEqual(len(result["requested_files"]), 0)
        
        # Check first edit
        path1, old1, new1 = result["edits"][0]
        self.assertEqual(path1, "./path/to/file1.py")
        self.assertEqual(old1, 'print("hello old world")')
        self.assertEqual(new1, 'print("hello new world")')
        
        # Check second edit
        path2, old2, new2 = result["edits"][1]
        self.assertEqual(path2, "another/file.txt")
        self.assertEqual(old2, "old line1\nold line2")
        self.assertEqual(new2, "new line1\nnew line2\nnew line3")


    def test_parse_missing_tags(self):
        """Test parsing when find or replace tags are missing."""
        response = """
<edit path="file3.py">
<find>only old</find>
</edit>
<edit path="file4.py">
<replace>only new</replace>
</edit>
        """
        
        result = self.parser.parse(response)
        
        self.assertEqual(len(result["edits"]), 2)
        
        # First edit with only find tag
        path1, old1, new1 = result["edits"][0]
        self.assertEqual(path1, "file3.py")
        self.assertEqual(old1, "only old")
        self.assertEqual(new1, "")
        
        # Second edit with only replace tag
        path2, old2, new2 = result["edits"][1]
        self.assertEqual(path2, "file4.py")
        self.assertEqual(old2, "")
        self.assertEqual(new2, "only new")

    def test_parse_malformed_replace_tag(self):
        """Test handling of malformed replace tags closed with </find>."""
        response = """
<edit path="./path/to/file.py">
<find>
A contiguous chunk of lines...
</find>
<replace>
The lines to replace...
</find>
</edit>
        """
        
        result = self.parser.parse(response)
        
        self.assertEqual(len(result["edits"]), 1)
        path, old_code, new_code = result["edits"][0]
        self.assertEqual(path, "./path/to/file.py")
        self.assertEqual(old_code, "A contiguous chunk of lines...")
        self.assertEqual(new_code, "The lines to replace...")

    def test_parse_no_edit_blocks(self):
        """Test parsing response with no edit blocks."""
        response = "This is just a regular response with no edit blocks."
        
        result = self.parser.parse(response)
        
        self.assertEqual(len(result["edits"]), 0)
        self.assertEqual(len(result["requested_files"]), 0)


    def test_parse_path_with_spaces(self):
        """Test that paths with spaces are handled correctly."""
        response = """
<edit path=" path with spaces/file.py ">
<find>old</find>
<replace>new</replace>
</edit>
        """
        
        result = self.parser.parse(response)
        
        self.assertEqual(len(result["edits"]), 1)
        path, old_code, new_code = result["edits"][0]
        self.assertEqual(path, "path with spaces/file.py")
        self.assertEqual(old_code, "old")
        self.assertEqual(new_code, "new")

    def test_parse_request_files_block(self):
        """Test parsing of request_files blocks."""
        response = """
Some text here.
<request_files>
./file1.py
./file2.py
./tests/test_file.py
</request_files>
More text here.
        """
        
        result = self.parser.parse(response)
        
        self.assertEqual(len(result["edits"]), 0)
        self.assertEqual(len(result["requested_files"]), 3)
        self.assertEqual(result["requested_files"], 
                        ["./file1.py", "./file2.py", "./tests/test_file.py"])

    def test_parse_request_files_with_empty_lines(self):
        """Test parsing request_files with empty lines and whitespace."""
        response = """
<request_files>
./file1.py

  ./file2.py  
    
./file3.py
</request_files>
        """
        
        result = self.parser.parse(response)
        
        self.assertEqual(len(result["requested_files"]), 3)
        self.assertEqual(result["requested_files"], 
                        ["./file1.py", "./file2.py", "./file3.py"])


    def test_parse_line_endings_normalization(self):
        """Test that line endings are normalized from CRLF to LF."""
        response = """
<edit path="file.py">
<find>line1\r\nline2</find>
<replace>new1\r\nnew2</replace>
</edit>
        """
        
        result = self.parser.parse(response)
        
        self.assertEqual(len(result["edits"]), 1)
        path, old_code, new_code = result["edits"][0]
        self.assertEqual(old_code, "line1\nline2")
        self.assertEqual(new_code, "new1\nnew2")

    def test_parse_multiple_edits_same_file(self):
        """Test parsing multiple edits targeting the same file."""
        response = """
<edit path="file.py">
<find>first</find>
<replace>1st</replace>
</edit>
<edit path="file.py">
<find>second</find>
<replace>2nd</replace>
</edit>
        """
        
        result = self.parser.parse(response)
        
        self.assertEqual(len(result["edits"]), 2)
        self.assertEqual(result["edits"][0][0], "file.py")
        self.assertEqual(result["edits"][1][0], "file.py")

    def test_parse_complex_xml_in_code(self):
        """Test parsing when the code itself contains XML-like syntax."""
        response = """
<edit path="file.py">
<find>print("<hello>")</find>
<replace>print("<world>")</replace>
</edit>
        """
        
        result = self.parser.parse(response)
        
        self.assertEqual(len(result["edits"]), 1)
        path, old_code, new_code = result["edits"][0]
        self.assertEqual(old_code, 'print("<hello>")')
        self.assertEqual(new_code, 'print("<world>")')

    def test_parse_nested_tags_in_code(self):
        """Test parsing when code contains strings with XML-like content."""
        response = """
<edit path="file.py">
<find>html = "<div><span>text</span></div>"</find>
<replace>html = "<div><p>text</p></div>"</replace>
</edit>
        """
        
        result = self.parser.parse(response)
        
        self.assertEqual(len(result["edits"]), 1)
        path, old_code, new_code = result["edits"][0]
        self.assertEqual(old_code, 'html = "<div><span>text</span></div>"')
        self.assertEqual(new_code, 'html = "<div><p>text</p></div>"')


if __name__ == '__main__':
    unittest.main()
