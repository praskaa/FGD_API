# -*- coding: utf-8 -*-
title = "MyButton"
doc = """Version = 1.0
Date    = 01.01.2026

Description:
Placeholder for pyRevit .pushbutton.
Use it as a base for your new pyRevit tool.

How-To:
1. Step 1...
2. Step 2...
3. Step 3...

To-Do:
[FEATURE] - Describe Your Feature...

Last Updates:
- [01.01.2026] v1.0 Initial version

Author: PrasKaa"""

from pyrevit import revit, forms, script

doc = revit.doc
output = script.get_output()
output.close_others()

output.print_md('# {}'.format(title))
output.print_md('My new pyRevit tool.')
