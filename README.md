# pydantic-to-go

## Quick Start

```
python ./script/convert_pydantic/trans.py --file=serializers.py --path=./openapi --dest=./validator --common=./openapi/validation/rules.py --tests=./openapi/tests/test_pydantic
```

## cli

```
python3 ./script/convert_pydantic/trans.py -h
usage: trans.py [-h] --file FILE [--path PATH] [--dest DEST] [--common COMMON] [--tests TESTS]

options:
  -h, --help       show this help message and exit
  --file FILE
  --path PATH
  --dest DEST
  --common COMMON
  --tests TESTS
```

```--file``` 

```--path``` 

```--dest```

```--common```

```--tests```