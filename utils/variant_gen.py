import random

def generate_gmail_variants(base_email: str, quantity: int = 10) -> list:
    """Generates pure randomized case variations for a base Gmail address (without dots)."""
    base_email = base_email.strip()
    if "@" not in base_email:
        return []
    
    user_part, domain = base_email.split("@", 1)
    clean_user = user_part.replace(".", "")
    
    variants = set()
    attempts = 0
    max_attempts = max(quantity * 40, 300)
    
    while len(variants) < quantity and attempts < max_attempts:
        attempts += 1
        chars = [c.upper() if random.random() > 0.5 else c.lower() for c in clean_user]
        variant_user = "".join(chars)
        full_email = f"{variant_user}@{domain}"
        variants.add(full_email)
        
    res = list(variants)
    while len(res) < quantity:
        chars = [c.upper() if random.random() > 0.5 else c.lower() for c in clean_user]
        res.append(f"{''.join(chars)}@{domain}")
        
    return res[:quantity]
