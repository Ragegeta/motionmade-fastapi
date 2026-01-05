from app.normalize import normalize_message

test_cases = [
    ('ur prices pls', 'your prices please'),
    ('wat areas do u cover', 'what areas do you cover'),
    ('can u come 2day', 'can you come today'),
    ('do u do ceiling fans', 'do you do ceiling fans'),
    ('r u licensed', 'are you licensed'),
    ('hey quick one - how much do you charge', 'how much do you charge'),
    ('g\'day mate wat do u charge', 'hello what do you charge'),
]

print('Normalization test:')
all_pass = True
for messy, expected in test_cases:
    result = normalize_message(messy)
    match = expected in result or result in expected  # Flexible match
    icon = '[PASS]' if match else '[FAIL]'
    if not match:
        all_pass = False
    print(f'  {icon} "{messy}"')
    print(f'       -> "{result}"')
    if not match:
        print(f'       Expected: "{expected}"')

print()
print('[PASS] All pass' if all_pass else '[FAIL] Some failures - normalization needs work')

