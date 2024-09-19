import lldb
import io
import os
import sys
import argparse
import signal
from dataclasses import dataclass, field
from typing import List


def log(*args, **kwargs):
    print(*args, **kwargs, flush=True)


@dataclass
class Test:
    source_file: str
    line_number: int
    variable: str
    expected_value: str


@dataclass
class TestResult:
    test: Test
    status: str
    actual: str = None
    message: str = None
    missing: set = None
    extra: set = None


@dataclass
class TestCase:
    source_file: str
    start_line: int
    end_line: int
    tests: List[Test]


@dataclass
class CaseResult:
    test_case: TestCase
    function: str
    results: List[TestResult]


@dataclass
class TestResults:
    total: int = 0
    passed: int = 0
    failed: int = 0
    case_results: List[CaseResult] = field(default_factory=list)


class LLDBDebugger:
    def __init__(self, executable_path, plugin_path=None):
        self.executable_path = executable_path
        self.plugin_path = plugin_path
        self.debugger = lldb.SBDebugger.Create()
        self.debugger.SetAsync(False)
        self.target = None
        self.process = None
        self.type_mapping = {
            'long': 'int',
            'unsigned long': 'uint',
            # Add more mappings as needed
        }

    def setup(self):
        if self.plugin_path:
            self.debugger.HandleCommand(
                f'command script import "{self.plugin_path}"')
        self.target = self.debugger.CreateTarget(self.executable_path)
        if not self.target:
            raise Exception(f"Failed to create target for {
                            self.executable_path}")

    def set_breakpoint(self, file_spec, line_number):
        breakpoint = self.target.BreakpointCreateByLocation(
            file_spec, line_number)
        if not breakpoint.IsValid():
            raise Exception(f"Failed to set breakpoint at {
                            file_spec}:{line_number}")
        return breakpoint

    def run_to_breakpoint(self):
        if not self.process:
            self.process = self.target.LaunchSimple(None, None, os.getcwd())
        else:
            self.process.Continue()
        if self.process.GetState() != lldb.eStateStopped:
            raise Exception("Process didn't stop at breakpoint")

    def get_variable_value(self, var_name):
        frame = self.process.GetSelectedThread().GetFrameAtIndex(0)

        if isinstance(var_name, lldb.SBValue):
            var = var_name
        else:
            actual_var_name = var_name.split('=')[0].strip()
            if '(' in actual_var_name:
                actual_var_name = actual_var_name.split('(')[-1].strip()
            var = frame.FindVariable(actual_var_name)

        return self.format_value(var)

    def format_value(self, var):
        if var.IsValid():
            type_name = var.GetTypeName()
            var_type = var.GetType()
            type_class = var_type.GetTypeClass()

            if type_name.startswith('[]'):  # Slice
                return self.format_slice(var)
            elif var_type.IsArrayType():
                if type_class in [lldb.eTypeClassStruct, lldb.eTypeClassClass]:
                    return self.format_custom_array(var)
                else:
                    return self.format_array(var)
            elif type_name == 'string':  # String
                return self.format_string(var)
            elif type_name in ['complex64', 'complex128']:
                return self.format_complex(var)
            elif type_class in [lldb.eTypeClassStruct, lldb.eTypeClassClass]:
                return self.format_struct(var)
            else:
                value = var.GetValue()
                summary = var.GetSummary()
                if value is not None:
                    return str(value)
                elif summary is not None:
                    return summary
                else:
                    return "None"
        return "None"

    def format_slice(self, var):
        length = int(var.GetChildMemberWithName('len').GetValue())
        data_ptr = var.GetChildMemberWithName('data')
        elements = []

        # Get the actual pointer value
        ptr_value = int(data_ptr.GetValue(), 16)
        element_type = data_ptr.GetType().GetPointeeType()
        element_size = element_type.GetByteSize()

        for i in range(length):
            element_address = ptr_value + i * element_size
            element = self.target.CreateValueFromAddress(
                f"element_{i}", lldb.SBAddress(element_address, self.target), element_type)
            value = self.format_value(element)
            elements.append(value)

        type_name = var.GetType().GetName().split(
            '[]')[-1]  # Extract element type from slice type
        type_name = self.type_mapping.get(type_name, type_name)  # Use mapping
        result = f"[]{type_name}[{', '.join(elements)}]"
        return result

    def format_array(self, var):
        elements = []
        for i in range(var.GetNumChildren()):
            value = self.format_value(var.GetChildAtIndex(i))
            elements.append(value)
        array_size = var.GetNumChildren()
        type_name = var.GetType().GetArrayElementType().GetName()
        type_name = self.type_mapping.get(type_name, type_name)  # Use mapping
        return f"[{array_size}]{type_name}[{', '.join(elements)}]"

    def format_custom_array(self, var):
        elements = []
        for i in range(var.GetNumChildren()):
            element = var.GetChildAtIndex(i)
            formatted = self.format_struct(element, include_type=False)
            elements.append(formatted)
        array_size = var.GetNumChildren()
        type_name = var.GetType().GetArrayElementType().GetName()
        return f"[{array_size}]{type_name}[{', '.join(elements)}]"

    def format_pointer(self, var):
        target = var.Dereference()
        if target.IsValid():
            return f"*{self.get_variable_value(target.GetName())}"
        else:
            return str(var.GetValue())

    def format_string(self, var):
        summary = var.GetSummary()
        if summary is not None:
            return summary.strip('"')
        else:
            data = var.GetChildMemberWithName('data').GetValue()
            length = int(var.GetChildMemberWithName('len').GetValue())
            if data and length:
                error = lldb.SBError()
                return self.process.ReadCStringFromMemory(int(data, 16), length + 1, error)
        return "None"

    def format_struct(self, var, include_type=True):
        children = []
        for i in range(var.GetNumChildren()):
            child = var.GetChildAtIndex(i)
            child_name = child.GetName()
            child_value = self.format_value(child)
            children.append(f"{child_name} = {child_value}")

        struct_content = f"({', '.join(children)})"
        if include_type:
            struct_name = var.GetTypeName()
            return f"{struct_name}{struct_content}"
        else:
            return struct_content

    def format_complex(self, var):
        real = var.GetChildMemberWithName('real').GetValue()
        imag = var.GetChildMemberWithName('imag').GetValue()
        return f"{var.GetTypeName()}(real = {real}, imag = {imag})"

    def get_all_variable_names(self):
        frame = self.process.GetSelectedThread().GetFrameAtIndex(0)
        return set(var.GetName() for var in frame.GetVariables(True, True, True, False))

    def get_current_function_name(self):
        frame = self.process.GetSelectedThread().GetFrameAtIndex(0)
        return frame.GetFunctionName()

    def cleanup(self):
        if self.process and self.process.IsValid():
            self.process.Kill()
        lldb.SBDebugger.Destroy(self.debugger)

    def run_console(self):
        log(
            "\nEntering LLDB interactive mode. Type 'quit' to exit and continue with the next test case.")
        log(
            "Use Ctrl+D to exit and continue, or Ctrl+C to abort all tests.")

        old_stdin, old_stdout, old_stderr = sys.stdin, sys.stdout, sys.stderr
        sys.stdin, sys.stdout, sys.stderr = sys.__stdin__, sys.__stdout__, sys.__stderr__

        self.debugger.SetAsync(True)
        self.debugger.HandleCommand("settings set auto-confirm true")
        self.debugger.HandleCommand("command script import lldb")

        interpreter = self.debugger.GetCommandInterpreter()
        continue_tests = True

        def keyboard_interrupt_handler(sig, frame):
            nonlocal continue_tests
            log("\nTest execution aborted by user.")
            continue_tests = False
            raise KeyboardInterrupt

        original_handler = signal.signal(
            signal.SIGINT, keyboard_interrupt_handler)

        try:
            while continue_tests:
                log("\n(lldb) ", end="")
                try:
                    command = input().strip()
                except EOFError:
                    log(
                        "\nExiting LLDB interactive mode. Continuing with next test case.")
                    break
                except KeyboardInterrupt:
                    break

                if command.lower() == 'quit':
                    log(
                        "\nExiting LLDB interactive mode. Continuing with next test case.")
                    break

                result = lldb.SBCommandReturnObject()
                interpreter.HandleCommand(command, result)
                log(result.GetOutput().rstrip(
                ) if result.Succeeded() else result.GetError().rstrip())

        finally:
            signal.signal(signal.SIGINT, original_handler)
            sys.stdin, sys.stdout, sys.stderr = old_stdin, old_stdout, old_stderr

        return continue_tests


def parse_expected_values(source_files):
    test_cases = []
    for source_file in source_files:
        with open(source_file, 'r') as f:
            content = f.readlines()
            i = 0
            while i < len(content):
                line = content[i].strip()
                if line.startswith('// Expected:'):
                    start_line = i + 1
                    tests = []
                    i += 1
                    while i < len(content):
                        line = content[i].strip()
                        if not line.startswith('//'):
                            break
                        parts = line.lstrip('//').strip().split(':', 1)
                        if len(parts) == 2:
                            var, value = map(str.strip, parts)
                            tests.append(Test(source_file, i + 1, var, value))
                        i += 1
                    end_line = i
                    test_cases.append(
                        TestCase(source_file, start_line, end_line, tests))
                else:
                    i += 1
    return test_cases


def run_tests(executable_path, source_files, verbose, interactive, plugin_path):
    debugger = LLDBDebugger(executable_path, plugin_path)
    test_cases = parse_expected_values(source_files)
    if verbose:
        log(
            f"Running tests for {', '.join(source_files)} with {executable_path}")
        log(f"Found {len(test_cases)} test cases")

    try:
        debugger.setup()
        results = execute_tests(debugger, test_cases, interactive)
        print_test_results(results, verbose)

        if results.total != results.passed:
            os._exit(1)

    except Exception as e:
        log(f"Error: {str(e)}")

    finally:
        debugger.cleanup()


def execute_tests(debugger, test_cases, interactive):
    results = TestResults()

    for test_case in test_cases:
        breakpoint = debugger.set_breakpoint(
            test_case.source_file, test_case.end_line)
        debugger.run_to_breakpoint()

        function_name = debugger.get_current_function_name()
        all_variable_names = debugger.get_all_variable_names()

        case_result = execute_test_case(
            debugger, test_case, all_variable_names)

        results.total += len(case_result.results)
        results.passed += sum(1 for r in case_result.results if r.status == 'pass')
        results.failed += sum(1 for r in case_result.results if r.status != 'pass')
        results.case_results.append(case_result)

        log(f"\nTest case: {case_result.test_case.source_file}:{
            case_result.test_case.start_line}-{case_result.test_case.end_line} in function '{case_result.function}'")
        for result in case_result.results:
            print_test_result(result, True)

        if interactive and any(r.status != 'pass' for r in case_result.results):
            log(
                "\nTest case failed. Entering LLDB interactive mode.")
            continue_tests = debugger.run_console()
            if not continue_tests:
                log("Aborting all tests.")
                break

            # After exiting the console, we need to ensure the process is in a valid state
            if debugger.process.GetState() == lldb.eStateRunning:
                debugger.process.Stop()
            elif debugger.process.GetState() == lldb.eStateExited:
                # If the process has exited, we need to re-launch it
                debugger.process = debugger.target.LaunchSimple(
                    None, None, os.getcwd())

        debugger.target.BreakpointDelete(breakpoint.GetID())

    return results


def execute_test_case(debugger, test_case, all_variable_names):
    results = []

    for test in test_case.tests:
        if test.variable == "all variables":
            result = execute_all_variables_test(test, all_variable_names)
        else:
            result = execute_single_variable_test(debugger, test)
        results.append(result)

    return CaseResult(test_case, debugger.get_current_function_name(), results)


def execute_all_variables_test(test, all_variable_names):
    expected_vars = set(test.expected_value.split())
    if expected_vars == all_variable_names:
        return TestResult(
            test=test,
            status='pass',
            actual=all_variable_names
        )
    else:
        return TestResult(
            test=test,
            status='fail',
            actual=all_variable_names,
            missing=expected_vars - all_variable_names,
            extra=all_variable_names - expected_vars
        )


def execute_single_variable_test(debugger, test):
    actual_value = debugger.get_variable_value(test.variable)
    if actual_value is None:
        log(f"Unable to fetch value for {test.variable}")
        return TestResult(
            test=test,
            status='error',
            message='Unable to fetch value'
        )

    # 移除可能的空格，但保留括号
    actual_value = actual_value.strip()
    expected_value = test.expected_value.strip()

    # 比较处理后的值
    if actual_value == expected_value:
        return TestResult(
            test=test,
            status='pass',
            actual=actual_value
        )
    else:
        return TestResult(
            test=test,
            status='fail',
            actual=actual_value
        )


def print_test_results(results: TestResults, verbose):
    for case_result in results.case_results:
        log(f"\nTest case: {case_result.test_case.source_file}:{
            case_result.test_case.start_line}-{case_result.test_case.end_line} in function '{case_result.function}'")
        for result in case_result.results:
            print_test_result(result, verbose)

    log("\nTest results:")
    log(f"  Total tests: {results.total}")
    log(f"  Passed tests: {results.passed}")
    log(f"  Failed tests: {results.failed}")
    if results.total == results.passed:
        log("All tests passed!")
    else:
        log("Some tests failed")


def print_test_result(result: TestResult, verbose):
    status_symbol = "✓" if result.status == 'pass' else "✗"
    status_text = "Pass" if result.status == 'pass' else "Fail"

    if result.status == 'pass':
        if verbose:
            log(
                f"{status_symbol} Line {result.test.line_number}, {result.test.variable}: {status_text}")
            if result.test.variable == 'all variables':
                log(f"    Variables: {
                    ', '.join(sorted(result.actual))}")
    else:  # fail or error
        log(
            f"{status_symbol} Line {result.test.line_number}, {result.test.variable}: {status_text}")
        if result.test.variable == 'all variables':
            if result.missing:
                log(
                    f"    Missing variables: {', '.join(sorted(result.missing))}")
            if result.extra:
                log(
                    f"    Extra variables: {', '.join(sorted(result.extra))}")
            log(
                f"    Expected: {', '.join(sorted(result.test.expected_value.split()))}")
            log(f"    Actual: {', '.join(sorted(result.actual))}")
        elif result.status == 'error':
            log(f"    Error: {result.message}")
        else:
            log(f"    Expected: {result.test.expected_value}")
            log(f"    Actual: {result.actual}")


def main():
    log(sys.argv)
    parser = argparse.ArgumentParser(
        description="LLDB 18 Debug Script with DWARF 5 Support")
    parser.add_argument("executable", help="Path to the executable")
    parser.add_argument("sources", nargs='+', help="Paths to the source files")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Enable verbose output")
    parser.add_argument("-i", "--interactive", action="store_true",
                        help="Enable interactive mode on test failure")
    parser.add_argument("--plugin", help="Path to the LLDB plugin")
    args = parser.parse_args()

    plugin_path = args.plugin or os.path.join(os.path.dirname(
        os.path.realpath(__file__)), "go_lldb_plugin.py")
    run_tests(args.executable, args.sources,
              args.verbose, args.interactive, plugin_path)


if __name__ == "__main__":
    main()


def run_commands(debugger, command, result, internal_dict):
    log(sys.argv)
    main()
    debugger.HandleCommand("quit")


def __lldb_init_module(debugger, internal_dict):
    # debugger.HandleCommand('command script add -f main.run_commands run_tests')
    pass
