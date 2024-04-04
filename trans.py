""" 
Pydantic to Go validator. Execute in the project root directory.

usage:
    python ./script/convert_pydantic/trans.py --file=serializers.py \
        --path=./openapi --dest=./validator \
        --common=./openapi/validation/rules.py \
        --tests=./openapi/tests/test_pydantic
"""
import ast
import re
import os
import argparse
import gostruct


# Used for go struct name deduplication.
class_set = set()
# Used for common function association to go validator.
register_validation = {}
# Test case data.
tests_data = {}

# Validator built-in check types.
validator_built_in_check = {
    "check_email": "email",
    "check_uuid": "uuid",
    "check_ip": "ip",
    "check_ipv6": "ipv6",
    "check_ipv4": "ipv4",
    "check_cidr": "cidr",
    "check_uuids": "dive,uuid,required",
    "check_ipv6s": "dive,ipv6,required",
    "check_ips": "dive,ip,required",
    "check_cidrs": "dive,cidr,required",
}


def generate_struct_name(class_def: ast.ClassDef, filename: str):
    """
    Generate a unique class name for the given Pydantic class definition.

    Args:
        class_def (ast.ClassDef): The Pydantic class definition.
        filename (str): The name of the Python file containing the class.

    Returns:
        str: The unique class name.
    """
    class_name = class_def.name
    if class_name in class_set:
        class_name = generate_name_with_file(class_name, filename)
    class_set.add(class_name)
    return class_name


def generate_name_with_file(name: str, filename: str):
    """
    Generate a unique class name for the given Pydantic class definition.

    Args:
        name (str): The base class name.
        filename (str): The name of the Python file containing the class.

    Returns:
        str: The unique class name.
    """
    return underline2hump(filename)+name


def build_tests_data(file_path: str):
    """
    Parse the test file and extract the test data.

    Args:
        file_path (str): The path to the test file.
    """
    with open(file_path, 'r', encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=file_path)
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        for func_node in node.body:  # ast.FuncDef
            success_data, fail_data = [], []
            class_name = ""
            for node in func_node.body:
                if isinstance(node, ast.Expr):
                    if isinstance(node.value.func, ast.Attribute):
                        continue
                    class_name = node.value.func.id
                    success_data.append(build_case_test_data(node))
                elif isinstance(node, ast.With):
                    if isinstance(node.body[0].value.func, ast.Attribute):
                        continue
                    class_name = node.body[0].value.func.id if not class_name else class_name
                    fail_data.append(build_case_test_data(node))
            if class_name in tests_data:
                class_name = generate_name_with_file(class_name,
                                                     file_path.split('/')[-1][:-3])
            tests_data[class_name] = {
                "success_data": success_data,
                "fail_data": fail_data,
            }


def build_case_test_data(node):
    """
    Build the test case data from the given node.

    Args:
        node (ast.AST): The node to extract the data from.

    Returns:
        dict: The test case data.
    """
    if isinstance(node, ast.Constant):
        return node.value
    elif isinstance(node, ast.Dict):
        data_item = {}
        keys, vals = node.keys, node.values
        for i, key in enumerate(keys):
            if isinstance(vals[i], ast.Constant):
                data_item[key.value] = vals[i].value
            else:
                data_item[key.value] = build_case_test_data(vals[i])
        return data_item
    elif isinstance(node, ast.List):
        data_item = []
        for item in node.elts:
            data_item.append(build_case_test_data(item))
        return data_item
    elif isinstance(node, ast.With):
        # Each with statement will only have one test case.
        return build_case_test_data(node.body[0])
    elif isinstance(node, ast.Expr):
        if not node.value.keywords:
            return {}
        else:
            return build_case_test_data(node.value.keywords[0].value)
    elif isinstance(node, ast.Call):
        return build_case_test_data(node.keywords[0].value)
    else:
        return {}


def pydantic_to_go_type(pydantic_type):
    """
    Convert a Pydantic type to a Go type.

    Args:
        pydantic_type (str): The Pydantic type, e.g., "str", "int", "List[str]".

    Returns:
        str: The Go type, e.g., "string", "int", "[]string".
    """
    type_map = {
        "str": "string",
        "int": "int",
        "float": "float64",
        "bool": "bool",
        "strictstr": "string",
        "conint": "int",
        "list": "[]",
        "ipv6address": "string",
        "strictint": "int",
        "strictbool": "bool",
        "dict": "map[string]string",
        "datetime": "string",
        "ipv4address": "string",
    }
    go_type = ""
    for val in pydantic_type:
        if val == "Optional":
            continue
        go_type += type_map.get(val.lower(), val)
    return go_type


def extract_pydantic_classes(file_path):
    """
    Extract the Pydantic classes from a Python file.

    :param file_path: The path to the Python file.
    :type file_path: str
    :return: A list of Pydantic class definitions.
    :rtype: list
    """
    with open(file_path, 'r', encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=file_path)

    pydantic_classes = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            pydantic_classes.append(node)
    return pydantic_classes


def extract_common_functions(file_path):
    """
    Extract the common functions from a Python file.

    Args:
        file_path (str): The path to the Python file.

    Returns:
        List[ast.FunctionDef]: A list of common function definitions.
    """
    with open(file_path, 'r', encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=file_path)

    functions = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            functions.append(node)
    return functions


def extract_pydantic_fields(class_name, class_def):
    """Extract the Pydantic fields from a class definition.

    Args:
        class_def (ast.ClassDef): The Pydantic class definition.

    Returns:
        List[Tuple[str, List[str], str]]: A list of Pydantic field definitions.
    """
    fields = []
    customs = {}
    for field in class_def.body:
        if isinstance(field, ast.Assign):
            field_name = field.value.func.args[0].value
            custom_func = field.value.args[0].id
            customs[field_name] = custom_func
    gostruct_fields = []
    for field in class_def.body:
        if isinstance(field, ast.AnnAssign):
            field_name = field.target.id
            field_types = get_field_type(field.annotation)

            kws = []
            for i, typ in enumerate(field_types):
                if isinstance(typ, tuple):
                    kws = typ[2]
                    field_types[i] = typ[0]
            required, json, tag = build_tag(field, field_types, kws, customs)
            fields.append((field_name, field_types, tag, json, required))
            sub_start = 2 if field_types[0] == "Optional"else 1
            go_type = gostruct.Type(cur=pydantic_to_go_type(field_types),
                                    sub=pydantic_to_go_type(field_types[sub_start:]))
            gostruct_fields.append(gostruct.Field(name=underline2hump(field_name),
                                                  typ=go_type,
                                                  json_name=json,
                                                  tag=tag,
                                                  required=required))
        elif isinstance(field, ast.Assign):
            pass
        elif isinstance(field, ast.FunctionDef):
            pass
    gostruct.structs[class_name] = gostruct.Struct(class_name, gostruct_fields)
    return fields


def get_field_type(annotation):
    """
    Extract the type information from a Pydantic annotation.

    Args:
        annotation (ast.AST): The Pydantic annotation node.

    Returns:
        list: A list of type information, where each item is 
            either a type name (str) or a tuple of (type name, args, kws).
    """
    if not annotation:
        return []
    elif isinstance(annotation, ast.Name):
        return [annotation.id]
    elif isinstance(annotation, ast.Call):
        return [(annotation.func.id, annotation.args, annotation.keywords)]
    elif isinstance(annotation, ast.Subscript):
        return [annotation.value.id]+get_field_type(annotation.slice)


def build_tag(field, field_types, kws, customs: dict):
    """
    Generate the Go struct tag for a Pydantic field.

    Args:
        field (ast.AnnAssign): The Pydantic field definition.
        field_types (List[str]): The field type information.
        kws (List[ast.keyword]): The field keyword arguments.

    Returns:
        str: The Go struct tag.
    """
    validations = []
    required = {"Optional": "omitempty"}.get(field_types[0], "required")
    json = field.target.id
    validations.append(required)
    if field.value:
        if isinstance(field.value, ast.Constant):
            # [fixme] TODO: Support default value.
            pass
        else:
            for kv in field.value.keywords+kws:
                if kv.arg == "alias":
                    json = kv.value.value
                elif kv.arg in ["min_length", "min_items"]:
                    validations.append("min=" + str(kv.value.value))
                elif kv.arg in ["max_length", "max_items"]:
                    if isinstance(kv.value, ast.Name):
                        validations.append("max=" + str(kv.value.id))
                    else:
                        validations.append("max=" + str(kv.value.value))
                elif kv.arg == "ge":
                    validations.append("gte=" + str(kv.value.value))
                elif kv.arg == "le":
                    if isinstance(kv.value, ast.Name):
                        validations.append("lte=" + str(kv.value.id))
                    else:
                        validations.append("lte=" + str(kv.value.value))
                elif kv.arg in ["gt", "exclusiveMinimum"]:
                    validations.append("gt=" + str(kv.value.value))
                elif kv.arg == "lt":
                    validations.append("lt=" + str(kv.value.value))
                elif kv.arg in ["strict", "default"]:
                    pass
                else:
                    raise ValueError(f"Unknown field {kv.arg}")
    if field.target.id in customs:
        check_func = customs[field.target.id]
        sub_tag = validator_built_in_check.get(check_func,
                                               check_func)
        validations.append(sub_tag)
    return required, json, "`json:\"" + json + "\" validate:\"" + ",".join(validations) + "\"`"


def convert_pydantic_to_go(pydantic_classes, filename: str):
    """
    Convert a list of Pydantic class definitions to Go code.

    Args:
        pydantic_classes (List[ast.ClassDef]): The list of Pydantic class definitions.
        filename (str): The name of the Python file containing the Pydantic classes.

    Returns:
        str: The Go code.
    """
    go_code = ""
    go_code_pkg = "package validator\n\n"

    go_code_import = "import (\n"
    go_code_import_end = ")\n\n"

    go_code_import_net = "\"net\"\n"
    go_code_import_time = "\"time\"\n"

    go_test_code = "package validator\n\n"
    go_test_code += "import (\n\t\"testing\"\n\n\t\"github.com/stretchr/testify/assert\"\n)\n\n"

    for class_def in pydantic_classes:
        # Verify whether go struct is repeatedly defined.
        class_name = generate_struct_name(class_def, filename)

        class_test_data = tests_data.get(class_name, {})
        success_data = class_test_data.get("success_data", [])
        fail_data = class_test_data.get("fail_data", [])
        print(class_name)
        go_code += f"type {class_name} struct {{\n"

        parents = ""
        if isinstance(class_def, ast.Name):
            parents = class_def.id
        else:
            parents = class_def.bases[0].id
        if "PaginationGetParamModel" in parents or "PaginationPostParamModel" in parents:
            go_code += "\tPaginationParamModel\n"

        fields = extract_pydantic_fields(class_name, class_def)
        for field_name, field_type, tag, _, required in fields:
            filed_type_go = pydantic_to_go_type(field_type)
            go_code += f"\t{underline2hump(field_name)} "
            # Using pointers to resolve ambiguities.
            # List and Map types do not require pointers.
            if required == "omitempty" and not filed_type_go.startswith("[]") \
                    and not filed_type_go.startswith("map["):
                go_code += "*"
            go_code += f"{filed_type_go} " + tag + "\n"
        go_code += "}\n\n"
        func_names = []
        for t in class_def.body:
            if isinstance(t, ast.FunctionDef):
                func_name = underline2hump(t.name)
                func_names.append(func_name)
                go_code += f"func (p *{class_name}){func_name} () error " + "{ \n" + \
                    "// TODO: need to be implemented. \n\n\treturn nil \n}\n\n"
        if func_names:
            go_code += f"func (p *{class_name})Check () error " + "{ \n"
            for func_name in func_names:
                go_code += f"\tif err := p.{func_name}(); err != nil "+"{\n"
                go_code += "\t\treturn err\n}\n\n"
            go_code += "\treturn nil \n}\n\n"
        # generate test code.
        go_test_code += f"func Test{class_name}(t *testing.T) {{\n"
        go_test_code += f"\t// case {1}.\n"
        go_test_code += f"\tparam := &{class_name}"+"{}\n"
        go_test_code += "\terr := ValidateStruct(param)\n"
        go_test_code += "\tassert.Error(t, err)\n\n"
        i = 2
        # success test cases.
        for success in success_data:
            go_test_code += f"\t// case {i}.\n"
            go_test_code += "\tparam = &"
            go_test_code += gostruct.build_go_data("required",
                                                   gostruct.structs[class_name],
                                                   success)

            go_test_code += "\n\terr = ValidateStruct(param)\n"
            go_test_code += "\tassert.NoError(t, err)\n\n"
            i += 1
        # failed test cases.
        for success in fail_data:
            go_test_code += f"\t// case {i}.\n"
            go_test_code += "\tparam = &"
            go_test_code += gostruct.build_go_data("required",
                                                   gostruct.structs[class_name],
                                                   success)

            go_test_code += "\n\terr = ValidateStruct(param)\n"
            go_test_code += "\tassert.Error(t, err)\n"
            go_test_code += "\t// TODO: Implement error checking\n\n"
            i += 1
        go_test_code += f"\t// case {i}.\n"
        go_test_code += "\t// TODO: need to be implemented.\n\n"
        go_test_code += "}\n\n"
    ans = go_code_pkg
    if "net." in go_code or "time." in go_code:
        ans += go_code_import
    if "net." in go_code:
        ans += go_code_import_net
    if "time." in go_code:
        ans += go_code_import_time
    if "net." in go_code or "time." in go_code:
        ans += go_code_import_end
    ans += go_code
    return ans, go_test_code


def underline2hump(underline_str: str):
    """
    Convert an underscore separated string to camelCase.

    Args:
        underline_str (str): The underscore separated string.

    Returns:
        str: The camelCase string.
    """
    sub = re.sub(r'(_\w)', lambda x: x.group(1)[1].upper(), underline_str)
    sub1, sub2 = sub[:1], sub[1:]
    return sub1.capitalize() + sub2


def convert_functions_to_go(functions):
    """
    Convert a list of Python functions to Go code.

    Args:
        functions (List[ast.FunctionDef]): The list of Python function definitions.

    Returns:
        str: The Go code.
    """
    go_code_pkg, go_test_code = "package validator\n\n", "package validator\n\n"
    go_code_import = "import (\n\t\"reflect\"\n\t\"sync\"\n\n\t\"github.com/go-playground/validator/v10\"\n)\n\n"
    go_code_var = "var (\n\tvalidate *validator.Validate\n\tonce sync.Once\n)\n\n"
    go_code = ""

    go_test_code += "import (\n\t\"testing\"\n\n\t\"github.com/go-playground/validator/v10\"\n)\n\n"

    go_code += "type CustomChecker interface {\n\tCheck() error \n}\n\n"
    go_code += "func ValidateStruct(s interface{}) error {\n"
    go_code += "\tifaceType := reflect.TypeOf((*CustomChecker)(nil)).Elem()\n"
    go_code += "\tif reflect.TypeOf(s).Implements(ifaceType) {\n"
    go_code += "\t\tfor i := 0; i < ifaceType.NumMethod(); i++ {\n"
    go_code += "\t\t\tmethod := ifaceType.Method(i)\n"
    go_code += "\t\t\tres := reflect.ValueOf(s).MethodByName(method.Name).Call(nil)\n"
    go_code += "\t\t\tif!res[0].IsNil() {\n"
    go_code += "\t\t\t\treturn res[0].Interface().(error)\n"
    go_code += "\t\t\t}\n"
    go_code += "\t\t}\n"
    go_code += "\t}\n"
    go_code += "\treturn GetValidate().Struct(s)\n"
    go_code += "}\n\n"

    go_code += "\tfunc IntPtr(v int)*int{\n\tans := v\n\treturn &ans\n\t}\n\n"
    go_code += "\tfunc Float64Ptr(v float64)*float64{\n\tans := v\n\treturn &ans\n\t}\n\n"
    go_code += "\tfunc BoolPtr(v bool)*bool{\n\tans := v\n\treturn &ans\n\t}\n\n"
    go_code += "\tfunc StringPtr(v string)*string{\n\tans := v\n\treturn &ans\n\t}\n\n"
    go_code += "\ttype PaginationParamModel struct {\n"
    go_code += "\tPageNo *int `json:\"page_no\" validate:\"omitempty,gte=1\"`\n"
    go_code += "\tPage *int `json:\"page\" validate:\"omitempty,gte=1\"`\n"
    go_code += "\tPageNumber *int `json:\"page_number\" validate:\"omitempty,gte=1\"`\n"
    go_code += "\tPageSize int `json:\"page_size\" validate:\"required,gte=1,lte=50\"`\n"
    go_code += "\t}\n\n"

    for func in functions:
        func_name = underline2hump(func.name)
        register_validation[func.name] = func_name
        go_code += f"func {func_name} (fl validator.FieldLevel) bool " + "{ \n" + \
            "// TODO: need to be implemented. \n\n\treturn true \n}\n\n"
        go_test_code += f"func Test{func_name}(t *testing.T) {{\n"
        go_test_code += "\t// case 1.\n"
        go_test_code += "\tvar param validator.FieldLevel"+"\n\n"
        go_test_code += "\t// TODO: need to be implemented. \n\n"
        go_test_code += f"\terr := {func_name}(param)\n" +\
            "\tt.Error(err)\n}\n\n"
    ans = go_code_pkg+go_code_import+go_code_var +\
        "func GetValidate() *validator.Validate {\n" \
        + "\tonce.Do(func(){\t \n\tvalidate = validator.New()\n\n"

    for k, v in register_validation.items():
        ans += f"\tvalidate.RegisterValidation(\"{k}\", {v})\n"

    ans += "\t})\n\n"

    ans += "\treturn validate\n}\n\n"
    ans += go_code
    return ans, go_test_code


def main(path: str, dest: str, file: str, common: str, tests: str):
    """Main function.

    Args:
        path (str): The path to the Python file.
        dest (str): The destination path for the generated Go code.
        file (str): The name of the Python file containing the Pydantic classes.
    """
    if not dest:
        dest = path

    if not os.path.exists(dest):
        os.makedirs(dest)

    if common:
        functions = extract_common_functions(common)
        go_code, go_test_code = convert_functions_to_go(functions)
        with open("./validator/common.go", 'w', encoding="utf-8") as f:
            f.write(go_code)
        with open("./validator/common_test.go", 'w', encoding="utf-8") as f:
            f.write(go_test_code)

        os.system("gofmt -w ./validator/common.go & gofmt -w ./validator/common_test.go")

    if tests:
        for root, _, files in os.walk(tests):
            for name in files:
                if name.endswith(".py") and name.startswith("test_"):
                    build_tests_data(root+'/'+name)

        for root, _, files in os.walk(path):
            for name in files:
                if file in name:
                    if root == ".":
                        filename = name
                    elif "/" in root:
                        filename = root.split("/")[-1]
                    else:
                        filename = name
                    pydantic_classes = extract_pydantic_classes(root+'/' + file)
                    for class_def in pydantic_classes:
                        class_name = generate_struct_name(class_def, filename)
                        extract_pydantic_fields(class_name, class_def)

        class_set.clear()

    for root, _, files in os.walk(path):
        for name in files:
            if file in name:
                print("Begin to convert: \n" + root + '/'+file + ': \n\nThese classes are being converted:')
                pydantic_classes = extract_pydantic_classes(root+'/' + file)
                if root == ".":
                    filename = name
                elif "/" in root:
                    filename = root.split("/")[-1]
                else:
                    filename = name
                go_code, go_test_code = convert_pydantic_to_go(pydantic_classes, filename)
                code_file = dest+"/"+filename+".go"
                with open(code_file, 'w', encoding="utf-8") as f:
                    f.write(go_code)
                code_test_file = dest+"/"+filename+"_test.go"
                with open(code_test_file, 'w', encoding="utf-8") as test_file:
                    test_file.write(go_test_code)

                os.system("gofmt -w "+code_file + " & gofmt -w "+code_test_file)
                print(f"\nConverted:\n {code_file}\n{code_test_file}\n")
                print("---------------------------------------------------\n\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", type=str, dest='file', required=True)
    parser.add_argument("--path", type=str, dest="path", default=".")
    parser.add_argument("--dest", type=str, dest="dest", default="")
    parser.add_argument("--common", type=str, dest="common", default="")
    parser.add_argument("--tests", type=str, dest="tests", default="")
    args = parser.parse_args()
    main(args.path, args.dest, args.file, args.common, args.tests)
