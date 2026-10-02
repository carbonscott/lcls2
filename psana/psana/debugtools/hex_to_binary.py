"""Script: convert the hexadecimal mask given as the first command-line argument to binary and print it, its length ('Total cores') and the indices of '0' bits counted from the least significant bit ('Disabled core indices').

The conversion and printing run at import time.
"""
import sys

def hex_to_binary(hex_str):
    # Remove '0x' prefix if present
    """Return the binary digits (without '0b') of the hexadecimal string ``hex_str``; the string is lower-cased and every '0x' occurrence is removed first."""
    hex_str = hex_str.lower().replace('0x', '')
    # Convert hex to int, then to binary, strip the '0b' prefix
    bin_str = bin(int(hex_str, 16))[2:]
    return bin_str

# Example usage:
hex_mask = sys.argv[1]
binary_mask = hex_to_binary(hex_mask)

print(f"Hex:    {hex_mask}")
print(f"Binary: {binary_mask}")
print(f"Total cores: {len(binary_mask)}")
print("Disabled core indices:", [i for i, b in enumerate(reversed(binary_mask)) if b == '0'])
