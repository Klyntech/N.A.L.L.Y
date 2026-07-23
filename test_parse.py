import re, json

text = '<tool_call>\n{"name": "system_health", "args": {}}\n</tool_call>'
pattern = r'<tool_call>\s*(\{.*?\})\s*</tool_call>'
matches = re.findall(pattern, text, re.DOTALL)
print("Matches:", matches)

# Test with the actual model output
text2 = '<tool_call>\n<function=system_health>\n</function>\n</tool_call>'
matches2 = re.findall(pattern, text2, re.DOTALL)
print("Matches2:", matches2)
