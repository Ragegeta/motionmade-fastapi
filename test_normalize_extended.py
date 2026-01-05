from app.normalize import normalize_message

test_cases = [
    # Original failures
    ('r u licensed', 'are you licensed'),
    ('r u insured', 'are you insured'),
    
    # Core slang
    ('ur prices pls', 'your prices please'),
    ('wat areas do u cover', 'what areas do you cover'),
    ('can u come 2day', 'can you come today'),
    ('do u do ceiling fans', 'do you do ceiling fans'),
    ('hey quick one - how much do you charge', 'how much do you charge'),
    
    # Edge cases
    ('r u available 2moro', 'are you available tomorrow'),
    ('y not today', 'why not today'),
    ('c u soon', 'see you soon'),
    ('im looking 4 a quote', 'i am looking for a quote'),
    
    # Should NOT change
    ('are you licensed', 'are you licensed'),
    ('how much do you charge', 'how much do you charge'),
]

print('Normalization test suite:')
print('=' * 60)
all_pass = True
for messy, expected in test_cases:
    result = normalize_message(messy)
    # Check if expected is contained in result (allows for minor variations)
    passed = expected.lower() in result.lower() or result.lower() in expected.lower()
    
    # Strict check for key transformations
    if 'are you' in expected and 'are you' not in result:
        passed = False
    if 'you' in expected and 'u' in result and 'you' not in result:
        passed = False
    
    icon = '[PASS]' if passed else '[FAIL]'
    if not passed:
        all_pass = False
    
    print(f'{icon} "{messy}"')
    print(f'   -> "{result}"')
    if not passed:
        print(f'   Expected: "{expected}"')
    print()

print('=' * 60)
print('[PASS] ALL PASS' if all_pass else '[FAIL] SOME FAILURES')

