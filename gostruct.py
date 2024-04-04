"""Golang structures."""
from typing import List


structs = {}

type_zeros = {
    "string": "",
    "int": 0,
    "float64": 0.0,
    "bool": "false",
}

ptr_func = {
    "int": "IntPtr",
    "float64": "Float64Ptr",
    "string": "StringPtr",
    "bool": "BoolPtr",
}


class Type(object):
    """
    The type of a field.
    """

    def __init__(self, cur: str = "", sub: str = ""):
        self.cur = cur
        self.sub = sub

    def is_base_type(self):
        """
        Returns whether the type is a base type or not.

        Returns:
            bool: True if the type is a base type, False otherwise.
        """
        return self.cur in type_zeros


class Field(object):
    """
    The field of a struct.
    """

    def __init__(self, name: str = "", typ: Type = None,
                 json_name: str = "", tag: str = "", required=""):
        self.name = name
        self.type = typ
        self.json_name = json_name
        self.tag = tag
        self.required = required


class Struct(object):
    """
    The go struct.
    """

    def __init__(self, name: str = "", fields: List[Field] = None):
        self.name = name
        self.fields = fields


def build_go_data(required: str, struct: Struct, data: dict):
    """
    This function takes in a required field, a struct, and a data dictionary.
    If the required field is "omitempty", the function prepends an "&" to the variable name.
    If the data dictionary is empty, the function returns a struct initialized to default values.
    Otherwise, the function returns a struct with its fields initialized to the corresponding values in the data dictionary.

    :param required: the required field of the struct
    :param struct: the struct to be initialized
    :param data: the data dictionary
    :return: the initialized struct
    """
    if not struct:
        return ""
    code = "\t"
    if required == "omitempty":
        code += "&"
    if not data:
        return code + struct.name+"{}"
    code += struct.name + "{\n"
    for field in struct.fields:
        sub_data = data.get(field.json_name)
        code += f"\t{field.name}: "
        if field.type.is_base_type():
            cur_code = ""
            if field.required == "omitempty":
                cur_code += ptr_func[field.type.cur]+"("
            if field.type.cur == "string":
                cur_code += f" \"{sub_data or type_zeros[field.type.cur]}\""
            elif field.type.cur == "bool":
                cur_code += "true" if sub_data else "false"
            elif field.type.cur == "int":
                try:
                    int(sub_data)
                except ValueError:
                    sub_data = type_zeros["int"]
                except TypeError:
                    sub_data = type_zeros["int"]
                cur_code += f"{sub_data}"
            else:
                cur_code += f"{sub_data or type_zeros[field.type.cur]}"
            if field.required == "omitempty":
                cur_code += ")"
            code += cur_code
        elif field.type.cur == "map[string]string":
            if not sub_data:
                code += "nil"
            else:
                code += "map[string]string{\n"
                for k, v in sub_data.items():
                    code += f"\"{k}\": \"{v}\",\n"
                code += "}\n"
        elif field.type.cur.startswith("[]"):
            if not sub_data:
                code += "nil"
            else:
                code += "[]"+field.type.sub+"{\n"
                if isinstance(sub_data, list):
                    for p_sub_data in sub_data:
                        if field.type.sub in structs:
                            ans = build_go_data(required="required",
                                                struct=structs[field.type.sub],
                                                data=p_sub_data)
                            code += ans
                        else:
                            if field.type.sub == "string":
                                code += f"\"{p_sub_data}\""
                            else:
                                code += f"{p_sub_data}"
                        if code.endswith("\n"):
                            code = code[:-1]
                        code += ",\n"
                else:
                    if field.type.sub in structs:
                        ans = build_go_data(required="required",
                                            struct=structs[field.type.sub],
                                            data=sub_data)
                        code += ans
                    else:
                        if field.type.sub == "string":
                            code += f"\"{sub_data}\""
                        else:
                            code += f"{sub_data}"
                code += "}"
        else:
            code += build_go_data(required=field.required,
                                  struct=structs[field.type.cur],
                                  data=sub_data)
        code += ",\n"
    code += "\t}"
    return code
