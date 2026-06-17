from bs4 import BeautifulSoup

class DOMParser:
    def __init__(self, html_content: str):
        self.soup = BeautifulSoup(html_content, 'html.parser')

    def extract_interactive_elements(self) -> list[dict]:
        elements = []
        
        # Find all buttons
        for button in self.soup.find_all('button'):
            elements.append({
                'element_type': 'button',
                'text': button.get_text(strip=True),
                'attributes': {
                    'id': button.get('id'),
                    'class': button.get('class'),
                    'name': button.get('name')
                }
            })
            
        # Find all links
        for link in self.soup.find_all('a'):
            elements.append({
                'element_type': 'a',
                'text': link.get_text(strip=True),
                'attributes': {
                    'id': link.get('id'),
                    'class': link.get('class'),
                    'href': link.get('href')
                }
            })
            
        # Find all input elements
        for input_tag in self.soup.find_all('input'):
            elements.append({
                'element_type': 'input',
                'text': None, # Inputs typically don't have text content
                'attributes': {
                    'id': input_tag.get('id'),
                    'class': input_tag.get('class'),
                    'name': input_tag.get('name'),
                    'type': input_tag.get('type'),
                    'placeholder': input_tag.get('placeholder')
                }
            })
            
        return elements