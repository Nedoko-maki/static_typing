import collections
import functools
import types

_error_msg_dict = {
    "_function": "object_type object_name's parameter 'param_name',",
    "_attribute": "object_type 'param_name' of object object_name,",
    "generic": " is not the same type as annotated: \nType given: p_type, type(s) expected: param_types",
    "dict_keys": " dict container's keys are not all of the type(s): param_types",
    "dict_values": " dict container's values are not all of the type(s): param_types",
    "container": " p_type container is not all of the type(s): param_types",
}

_type_tuple = collections.namedtuple("type_container",
                                     ["object_name", "object_type", "param_name", "param_types", "param_value"])


def _fmt_msg(msg, tc, override=None):
    if "param_type" in msg:
        msg = msg.replace("p_type", str(type(tc.param_value)))

    if not override:
        override = {}

    for (attr, value) in tc._asdict().items():  # this was the quickest/simplest way I found to convert this into a dict
        if attr not in override:
            if attr != "param_types":
                msg = msg.replace(attr, str(value))
            else:
                msg = msg.replace(attr, str(value.original_types))
        else:
            msg = msg.replace(attr, str(tuple(override[attr])))
    return msg


def _error_msg(err_type, tc, override=None):
    prefix = _error_msg_dict["_function"] if tc.object_type in ["function", "method"] else _error_msg_dict["_attribute"]
    err = prefix + _error_msg_dict[err_type]

    return _fmt_msg(err, tc, override)


class _TypeWrapper:
    def __init__(self, _type):

        self.original_type = _type

        if issubclass(type(_type), types.UnionType):  # if the type given is a union type.
            self.base_type = None
            self.subscript_types = _type.__args__

        elif isinstance(_type, types.GenericAlias):  # if the type given is a generic alias type.

            self.base_type = _type.__origin__
            self.subscript_types = _type.__args__

            if issubclass(self.base_type, dict) and len(self.subscript_types) == 2:
                # handling dict[key_type, value_type] types.
                self.subscript_types = tuple((_TypeWrapper(i),) for i in self.subscript_types)

            elif isinstance(*self.subscript_types, types.UnionType):
                self.subscript_types = self.subscript_types[0].__args__
        else:
            self.base_type = _type
            self.subscript_types = None
        # print(f"BASE: {self.base_type}, SUBSCRP: {self.subscript_types}")


class _TypeContainer:
    def __init__(self, _type):

        self.types: dict[set] = dict()
        self.original_types = _type

        for type_ in self._unpack_type(_type):
            if type_.base_type not in self.types:
                self.types[type_.base_type] = {type_}
            else:
                self.types[type_.base_type].add(type_)

    @staticmethod
    def _unpack_type(_type):
        if isinstance(_type, types.UnionType):
            return tuple(_TypeWrapper(i) for i in _type.__args__)
        else:
            return _TypeWrapper(_type),


def _validate_type(tc):
    if not issubclass(type(tc.param_value),  # if the param value type not in the param_types var.
                      tuple(tc.param_types.types)):
        raise TypeError(_error_msg("generic", tc))

    err = _validate_type_wrapper(tc)
    if err:
        raise TypeError(err)


def _validate_type_wrapper(tc):
    # print(tc.param_types.types, tc.param_value)
    if type(tc.param_value) not in tc.param_types.types:
        return  # meaning the value is a class instance, since it's subclassed from object and is not in the types set.

    for type_ in tc.param_types.types[type(tc.param_value)]:
        if not type_.subscript_types:  # if not a generic alias, regardless if it's a container,
            # return since that's a type match.
            return
        else:
            if issubclass(type_.base_type, dict) and len(type_.subscript_types) == 2:
                if isinstance(tc.param_value, dict):
                    # if type to be checked is dict, the subscript params is 2 and the type of the param value is dict.
                    #  Checking dict[key_type, value_type]

                    ga_unpacked_0 = type_.subscript_types[0][0].subscript_types if \
                        type_.subscript_types[0][
                            0].subscript_types else (type_.subscript_types[0][0].base_type,)
                    ga_unpacked_1 = type_.subscript_types[1][0].subscript_types if \
                        type_.subscript_types[1][
                            0].subscript_types else (type_.subscript_types[1][0].base_type,)

                    # this is the spawn of lucifer.

                    if not all((True if type(i) in ga_unpacked_0 else False for i in tc.param_value)):
                        return _error_msg("dict_keys", tc, override={"param_types": [*ga_unpacked_0]})
                    if not all((True if type(i) in ga_unpacked_1 else False for i in tc.param_value.values())):
                        return _error_msg("dict_values", tc, override={"param_types": [*ga_unpacked_1]})

                    return  # if the dict is a dict, and has all the correct subscripted types in key and values.

            elif not all((True if type(i) in type_.subscript_types else False for i in tc.param_value)):
                # Check if the generic alias container's values are all the specified type(s).
                return _error_msg("container", tc, override={"param_types": type_.subscript_types})


def static_type(f):
    """
    Decorator for static-typing function parameters. Annotate the type each parameter is meant to be, and if any
    given parameter isn't of the expected type, it will raise a TypeError.

    Supports normal types, union types, and container subscript types, and methods. Does not support nested generic
    aliases within generic aliases (Recursion needed, but that might make this a bit slow).
    """

    @functools.wraps(f)  # this helps with the identity of the passed function f.
    def wrapper(*args, **kwargs):

        obj_type = "method" if (args and hasattr(args[0], f.__name__)) \
            else "function" if isinstance(f, types.FunctionType) else "attribute"

        # Checking if a method of a class, don't include "self"/object ref in the
        # type checking. Have to resort to this jank because inspect.ismethod fails because it doesn't have a
        # __self__ attribute for some reason when passed into the decorator. Something to do with this being
        # before __init__ is called?

        _is_static = True if obj_type == "method" and issubclass(f.__class__, staticmethod) else False

        if not _is_static: 
            param_names = f.__code__.co_varnames[:f.__code__.co_argcount]
        else:
            param_names = f.__func__.__code__.co_varnames[:f.__func__.__code__.co_argcount]
            args = args[1:]  # exclude first arg, i.e. self. THIS WILL BREAK IF YOU TYPEHINT THE SELF VAR.

        concat_args = args + tuple(kwargs.values())
        annotated_args = tuple(  # if a param has a typehint: unpack it, else if it doesn't: unpack with an object type.
            (param_name, _TypeContainer(f.__annotations__[param_name])) if param_name in f.__annotations__ else (
                param_name, _TypeContainer(object)) for param_name in param_names)

        for param_args, param_value in zip(annotated_args, concat_args):
            param_name, param_types = param_args
            _validate_type(_type_tuple(f.__name__, obj_type, param_name, param_types, param_value))

        retval = f(*args, **kwargs)

        if "return" in f.__annotations__:
            param_types = _TypeContainer(f.__annotations__["return"])
            _validate_type(_type_tuple(f.__name__, obj_type, "return", param_types, retval))

        return retval

    return wrapper


def _is_user_method(attr, value):
    if "__" not in attr and getattr(value, 'decorate', True):
        if isinstance(value, staticmethod) and isinstance(value.__func__, types.FunctionType):
            return True
        return isinstance(value, types.FunctionType)
    return False


def dont_static_type(f):  # decorator to exclude static-typing methods of a class inherited from StaticBase.
    f.decorate = False
    return f


class StaticBase:
    """
    To use, first inherit from StaticBase. 
    
    Then annotate here, like:
    x: int
    y: str

    ...then add these attributes in the __init__ method to make them static-typed.
    THIS WILL ONLY STATIC-TYPE THE ATTRIBUTES WHEN BEING ASSIGNED TO (i.e. _setattr_).
    IT WILL NOT PROTECT AN ATTRIBUTE WHEN MUTATING ITSELF.
    """

    def __new__(cls, *args, **kwargs):
        for attr, value in cls.__dict__.items():
            if _is_user_method(attr, value):
                setattr(cls, attr, static_type(value))
        return super(StaticBase, cls).__new__(cls)

    def __setattr__(self, attr, value):
        if attr in self.__annotations__:
            param_types = _TypeContainer(self.__annotations__[attr])
            _validate_type(_type_tuple(self, "attribute", attr, param_types, value))
        self.__dict__[attr] = value
