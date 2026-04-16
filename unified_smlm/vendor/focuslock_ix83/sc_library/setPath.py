#!/usr/bin/python
#
## @file
#
# Add the storm-control directory that this module is located in to
# sys.path, remove any default storm-control directory (if it exists).
#
# Hazen 05/14
#

import os
import sys


# print("sys.path_0:\n",sys.path) 

sc_directory = os.path.abspath(__file__)
# print("sc_directory:\n",sc_directory)

for i in range(2):
    sc_directory = os.path.split(sc_directory)[0]

# Remove the default storm-control directories (if it exists).
for elt in sys.path:
    if (elt.endswith("storm-control")):
        sys.path.remove(elt)

# print("sys.path_1:\n",sys.path) 

# Add the new storm-control directory.
sys.path.append(sc_directory)
# print("sys.path_2:\n",sys.path) 

#
# The MIT License
#
# Copyright (c) 2015 Zhuang Lab, Harvard University
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
#
