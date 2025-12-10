import re
from bs4 import BeautifulSoup

def clean_html_content(html_content):
    """
    Clean and process HTML content by:
    1. Removing code block markers (```html and ```)
    2. Removing HTML comments
    3. Removing empty tags
    4. Cleaning up extra whitespace
    5. Removing image placeholders
    """
    if not html_content:
        return ""
        
    # Remove code block markers
    clean_content = re.sub(r'```(html)?\n?', '', html_content)
    
    # Remove HTML comments
    clean_content = re.sub(r'<!--.*?-->', '', clean_content, flags=re.DOTALL)
    
    # Parse with BeautifulSoup for HTML processing
    soup = BeautifulSoup(clean_content, 'html.parser')
    
    # Remove image placeholders
    for img_placeholder in soup.find_all(text=re.compile(r'\[IMAGE:.*?\]')):
        img_placeholder.replace_with('')
    
    # Remove empty tags
    for tag in soup.find_all():
        if not tag.get_text(strip=True) and not tag.find(True):
            tag.decompose()
    
    # Clean up whitespace
    clean_text = ' '.join(soup.get_text().split())
    
    return clean_text

def generate_content_prompt(content_type, topic, language="French", **kwargs):
    """
    Generate a clean prompt for content generation
    """
    prompt = f"""
    Please generate a {content_type} about "{topic}" in {language}.
    
    Requirements:
    - Write in a professional, engaging tone
    - Use proper HTML formatting
    - Do not include code block markers (```html or ```)
    - Do not include comments or placeholders
    - Ensure all HTML tags are properly closed
    - Keep the content focused and well-structured
    """
    
    # Add any additional requirements from kwargs
    for key, value in kwargs.items():
        if value:
            prompt += f"\n- {value}"
    
    return prompt.strip()
