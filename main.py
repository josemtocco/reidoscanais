def setup_selenium():
    """Configura o Chrome headless para capturar requests de rede."""
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--window-size=1920,1080')
    chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
    
    # Habilita logging de performance para capturar requests
    chrome_options.set_capability('goog:loggingPrefs', {'performance': 'ALL'})
    
    try:
        # Usa o chromedriver que já está instalado no PATH pelo GitHub Actions
        driver = webdriver.Chrome(options=chrome_options)
        return driver
    except Exception as e:
        print(f"⚠️ Erro ao iniciar Chrome: {e}")
        return None