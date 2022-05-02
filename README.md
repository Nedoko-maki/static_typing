# static_typing

A script where you can import the decorator @static_type to static-type functions. Typehint the arguments, and it will tell you if any args are not of the expected types.

Works with classes, by inheriting from the StaticBase class (it will static-type all attributes and methods). 
If you want to exclude any methods from static-typing, use the @dont_static_type decorator.

Ex:

class A(StaticBase):
    
    x: int
    y: str
    
    def __init__(self, x, y):
        self.x, self.y = x, y
