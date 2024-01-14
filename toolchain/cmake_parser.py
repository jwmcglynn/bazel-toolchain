#!/bin/python3

import argparse
import typing
import re

args_parser = argparse.ArgumentParser(
    description="Parses libclang cmake files and outputs bzl cc_library rules"
)
args_parser.add_argument(
    "filenames", type=str, nargs="+", help="Paths to libclang cmake files"
)


def extract_libraries(
    contents: str,
) -> typing.Dict[str, typing.List[str]]:
    """
    Searches for all `add_library` and `set_target_properties` calls and returns a list of tuples
    containing the library name and an array of library deps.

    ```
    add_library(LLVMSystemZAsmParser STATIC IMPORTED)

    set_target_properties(LLVMSystemZAsmParser PROPERTIES
      INTERFACE_LINK_LIBRARIES "LLVMMC;LLVMMCParser;LLVMSupport;LLVMSystemZDesc;LLVMSystemZInfo"
    )
    ```

    Returns {"LLVMSystemZAsmParser": ["LLVMMC", "LLVMMCParser", "LLVMSupport", "LLVMSystemZDesc", "LLVMSystemZInfo"]}

    Args:
        contents (str): Contents of the cmake file

    Returns:
        Dict[str, List[str]: A list of tuples containing the library name and an array of library deps
    """
    add_library_pattern = r"add_library\((\w+) [^\)]*\)"
    add_library_matches = re.findall(add_library_pattern, contents, re.DOTALL)

    # Regular expression pattern to match the set_target_properties call
    set_target_properties_pattern = r'set_target_properties\((\w+) PROPERTIES[\s\r\n]+INTERFACE_LINK_LIBRARIES "(.*?)"[^\)]*\)'
    set_target_properties_pattern_matches = re.findall(
        set_target_properties_pattern, contents, re.DOTALL
    )

    result = {}

    for library_name in add_library_matches:
        result[library_name] = []

    for match in set_target_properties_pattern_matches:
        library_name, deps_str = match
        deps = deps_str.split(";")

        # If a dep matches the syntax "\$<LINK_ONLY:clangAST>", then remove the "$<LINK_ONLY:" and ">" parts with a regex.
        deps = [re.sub(r"\\\$<LINK_ONLY:(.*?)>", r"\1", dep) for dep in deps]

        # Remove duplicate deps.
        deps = list(dict.fromkeys(deps))

        result[library_name] = deps

    return result


def cmake_parser(filename: str) -> str:
    """
    Loads the file and calls `extract_libraries` to parse libraries out, then formats those as a .bzl
    file.

    For example, the following cmake file:

    ```
    set_target_properties(LLVMSystemZAsmParser PROPERTIES
      INTERFACE_LINK_LIBRARIES "LLVMMC;LLVMMCParser;LLVMSupport;LLVMSystemZDesc;LLVMSystemZInfo"
    )
    ```

    Will be converted to:

    ```
    cc_library(
        name = "LLVMSystemZAsmParser",
        srcs = [
            "libs/libLLVMSystemZAsmParser.a",
        ],
        deps = [
            ":LLVMMC",
            ":LLVMMCParser",
            ":LLVMSupport",
            ":LLVMSystemZDesc",
            ":LLVMSystemZInfo",
        ],
    )
    ```

    Args:
        filename (str): Path to the cmake file

    Returns:
        str: Contents of the .bzl file to be written
    """
    # Load the contents of the input file
    with open(filename, "r") as f:
        contents = f.read()

    # Call the extract_libraries function with the contents
    libraries = extract_libraries(contents)

    # Initialize the .bzl file content as an empty string
    bzl_content = ""

    # Replace ["m", "ZLIB::ZLIB", "zstd::libzstd_static", ...] deps with
    # the relevant system library linkopts.
    system_library_map = {
        "m": "-lm",
        "ZLIB::ZLIB": "-lz",
        "Terminfo::terminfo": "-lncurses",
        "LibEdit::LibEdit": "-ledit",
        "LibXml2::LibXml2": "-lxml2",
        "-framework CoreServices": "-framework CoreServices",
        "rt": "-lrt",
        "dl": "-ldl",
        "-lpthread": "-lpthread",
    }

    dep_map = {
        "zstd::libzstd_static": "@zstd",
        "zstd::libzstd_shared": "@zstd",
    }

    # Iterate through the libraries and format the output as a .bzl file
    for lib_name, lib_deps in libraries.items():
        link_opts = []
        external_deps = []
        internal_deps = []

        for dep in lib_deps:
            if dep in system_library_map:
                link_opts.append(system_library_map[dep])
            elif dep in dep_map:
                external_deps.append(dep_map[dep])
            else:
                internal_deps.append(dep)

        bzl_content += f"cc_library(\n"
        bzl_content += f'    name = "lib_{lib_name}",\n'
        bzl_content += f"    srcs = [\n"
        bzl_content += f'        "lib/lib{lib_name}.a",\n'
        bzl_content += f"    ],\n"

        if len(internal_deps) != 0 or len(external_deps) != 0:
            bzl_content += f"    deps = [\n"
            for dep in internal_deps:
                bzl_content += f'        ":lib_{dep}",\n'
            for dep in external_deps:
                bzl_content += f'        "{dep}",\n'
            bzl_content += f"    ],\n"

        if len(link_opts) != 0:
            bzl_content += f"    linkopts = [\n"
            for link_opt in link_opts:
                bzl_content += f'        "{link_opt}",\n'
            bzl_content += f"    ],\n"

        bzl_content += f")\n\n"

    return bzl_content


if __name__ == "__main__":
    args = args_parser.parse_args()
    for filename in args.filenames:
        print("# Source: " + filename)
        print(cmake_parser(filename))
