"""Publish the original product HTML under a CSP without inline JavaScript."""
from html.parser import HTMLParser
from html import escape
from pathlib import Path
import hashlib
import re
import sys

class ProductBundle(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.output, self.scripts, self.handlers = [], [], []
        self.in_script = False

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == 'script' and not attributes.get('src'):
            self.in_script = True
            return
        events = [(k[2:], v) for k,v in attrs if k.startswith('on')]
        attrs = [(k,v) for k,v in attrs if not k.startswith('on')]
        if events:
            key = str(len(self.handlers))
            attrs.append(('data-noteai-events', key))
            self.handlers.append((key, events))
        rendered = ''.join(' ' + k + ('' if v is None else '="' + escape(v, quote=True) + '"') for k,v in attrs)
        self.output.append('<' + tag + rendered + '>')

    def handle_endtag(self, tag):
        if tag == 'script' and self.in_script:
            self.in_script = False
            self.output.append('<script src="/assets/product-app.js"></script><script src="/assets/product-events.js"></script>')
        else:
            self.output.append('</' + tag + '>')

    def handle_data(self, data):
        (self.scripts if self.in_script else self.output).append(data)
    def handle_entityref(self, name): self.output.append('&' + name + ';')
    def handle_charref(self, name): self.output.append('&#' + name + ';')
    def handle_comment(self, data): self.output.append('<!--' + data + '-->')
    def handle_decl(self, decl): self.output.append('<!' + decl + '>')


def build(directory, *, version_product_app=False):
    root = Path(directory)
    parser = ProductBundle()
    parser.feed((root/'index.html').read_text())
    app = ''.join(parser.scripts).encode('utf-8')
    index = ''.join(parser.output)
    if version_product_app:
        version = hashlib.sha256(app).hexdigest()[:12]
        index = index.replace('src="/assets/product-app.js"', f'src="/assets/product-app.js?v={version}"')
        payment_script = root/'assets/payment-native.js'
        if payment_script.is_file():
            payment_version = hashlib.sha256(payment_script.read_bytes()).hexdigest()[:12]
            index = index.replace('src="/assets/payment-native.js"', f'src="/assets/payment-native.js?v={payment_version}"')
    (root/'index.html').write_text(index)
    (root/'assets/product-app.js').write_bytes(app)
    lines = []
    for key, events in parser.handlers:
        for event, code in events:
            if not re.fullmatch('[a-z]+',event): raise ValueError('invalid event')
            lines.append(f'''document.querySelector('[data-noteai-events="{key}"]').addEventListener('{event}', function(event) {{
  const result = (function(event) {{ {code} }}).call(this, event);
  if (result === false) event.preventDefault();
}});''')
    (root/'assets/product-events.js').write_text('\n'.join(lines)+'\n')

if __name__ == '__main__': build(sys.argv[1], version_product_app='--version-product-app' in sys.argv[2:])
