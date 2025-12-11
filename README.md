 # newscli
 
 A terminal TUI news reader that pulls from RSS feeds, shows authors when available, and provides lightweight **content-based** heuristics about tone/subjectivity.
 
 It does **not** scrape personal background information (e.g., LinkedIn). If you want to research an author, the app only generates search links you can open yourself.
 
 ## Install
 
```bash
pip install .
```

Editable installs may work too if your pip/setuptools support it:

```bash
pip install -e .
```
 
 ## Run
 
 ```bash
 news
 ```
 
 ## Keys
 
- `↑/↓` or `j/k`: move
- `enter`: open selected article reader
- `b`: open selected article in browser
- `r`: refresh current source
- `a`: show author research links
- `q`: quit
 
 ## Sources
 
 Default sources are built in. You can add your own RSS feeds in:
 
 `~/.config/newscli/sources.json`
 
 Example:
 
 ```json
 [
   {"name": "My Blog", "url": "https://example.com/rss.xml"},
   {"name": "Tech News", "url": "https://news.ycombinator.com/rss"}
 ]
 ```
# newstui
