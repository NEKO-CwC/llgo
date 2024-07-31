package main

import (
	"crypto/sha512"
	"fmt"
	"io"
)

func main() {
	h := sha512.New()
	io.WriteString(h, "The fog is getting thicker!")
	io.WriteString(h, "And Leon's getting laaarger!")
	fmt.Printf("%x", h.Sum(nil))
}
