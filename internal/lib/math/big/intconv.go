/*
 * Copyright (c) 2024 The GoPlus Authors (goplus.org). All rights reserved.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

package big

import (
	"github.com/goplus/llgo/c"
	"github.com/goplus/llgo/c/openssl"
)

/*
// Text returns the string representation of x in the given base.
// Base must be between 2 and 62, inclusive. The result uses the
// lower-case letters 'a' to 'z' for digit values 10 to 35, and
// the upper-case letters 'A' to 'Z' for digit values 36 to 61.
// No prefix (such as "0x") is added to the string. If x is a nil
// pointer it returns "<nil>".
func (x *Int) Text(base int) string {
}

// Append appends the string representation of x, as generated by
// x.Text(base), to buf and returns the extended buffer.
func (x *Int) Append(buf []byte, base int) []byte {
}
*/

// String returns the decimal representation of x as generated by
// x.Text(10).
func (x *Int) String() string {
	// TODO(xsw): can optimize it?
	cstr := (*openssl.BIGNUM)(x).CStr()
	ret := c.GoString(cstr)
	openssl.FreeCStr(cstr)
	return ret
}

/*
// Format implements fmt.Formatter. It accepts the formats
// 'b' (binary), 'o' (octal with 0 prefix), 'O' (octal with 0o prefix),
// 'd' (decimal), 'x' (lowercase hexadecimal), and
// 'X' (uppercase hexadecimal).
// Also supported are the full suite of package fmt's format
// flags for integral types, including '+' and ' ' for sign
// control, '#' for leading zero in octal and for hexadecimal,
// a leading "0x" or "0X" for "%#x" and "%#X" respectively,
// specification of minimum digits precision, output field
// width, space or zero padding, and '-' for left or right
// justification.
func (x *Int) Format(s fmt.State, ch rune) {
}

// Scan is a support routine for fmt.Scanner; it sets z to the value of
// the scanned number. It accepts the formats 'b' (binary), 'o' (octal),
// 'd' (decimal), 'x' (lowercase hexadecimal), and 'X' (uppercase hexadecimal).
func (z *Int) Scan(s fmt.ScanState, ch rune) error {
}
*/
