"""Windows source-free builder using OpenCV's native API without its source loader."""
from pathlib import Path
import sys


def native_opencv_arguments(arguments, native_file):
    native = Path(native_file).resolve()
    if native.suffix.casefold() != '.pyd' or not native.is_file():
        raise RuntimeError('OpenCV besitzt keine prüfbare native Windows-Erweiterung.')
    result = []
    iterator = iter(arguments)
    collection = {'--collect-submodules', '--collect-all', '--hidden-import'}
    for argument in iterator:
        if any(argument == option + '=cv2' for option in collection):
            continue
        if argument in collection:
            value = next(iterator)
            if value != 'cv2':
                result.extend((argument, value))
        else:
            result.append(argument)
    result.extend(('--exclude-module', 'cv2', '--add-binary', str(native) + ';.'))
    return result


def main(arguments=None):
    import cv2
    from PyInstaller.__main__ import run
    # Importing the installed loader also establishes its native DLL search paths
    # for dependency collection, without changing files in the installed package.
    native = getattr(cv2, '_native', cv2)
    arguments = sys.argv[1:] if arguments is None else arguments
    run(native_opencv_arguments(arguments, native.__file__))


if __name__ == '__main__':
    main()
