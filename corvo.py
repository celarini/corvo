import os
import time
import zipfile
import requests
import shutil
import hashlib
import json
import logging
from datetime import datetime
from colorama import init, Fore, Style
import keyboard
import tkinter
from tkinter.filedialog import askdirectory


init()


CONFIG_FILE = "game_saves_config.json"
MAX_ZIP_SIZE = 8 * 1024 * 1024  # 8 MB
LOG_FILE = "log.txt"
SAVE_FILE_EXTENSIONS = ('.sav', '.dat', '.json', '.ini', '.txt', '.cfg', '.profile', '.存档') # Add more extensions if needed

# Config do logging
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger()
logger.handlers[0].stream = open(LOG_FILE, 'a')

# Arte ASCII
BANNER_LINES = """
..---#+#++#+------++###########-----------+##
...--++#++#++---################+---------++#
...----+++++---##################+---------+#
....--+##+++--####################----------+
....--+++-+---##+-################+---------
.....---------##..-###############+---------
.....---------+#++#########+-######+--------
.....----------##-##########-+#####+--------
......----------++--########-#######--------
......----------+#--+#######+########-------
.......----------#+-+################+------
.......----------+++########+-########-----
.......-----------#####################----
.......-----------+#+#+################+---
......------------+###+#################----
......-----------+#+-----###############+---
.....-----------+##+-----+###############----
.....---------+###+----+++###############+---
....---------#####+---++++################---
....--------#####-+--+++-+################+--
...--------+#####-+--+#--#################+--
...---------######+-+++--#################+-+
..----------+######++#+-+#################++#
"""

# Frase pirata
PIRATE_FULL_LINES = [
    "A pirataria é a chama",
    "da liberdade, acesa",
    "pelos que têm pouco",
    "contra o jugo de um",
    "capitalismo que sempre",
    "privilegia os abastados",
    "e nega aos humildes o",
    "mesmo direito de sonhar."
]

PIRATE_CENSORED_LINES = [
    "A ****** é a chama",
    "da liberdade,",
    "*******************",
    "contra o jugo de um",
    "capitalismo que",
    "******************",
    "e nega aos ****** o",
    "mesmo direito de sonhar."
]

def generate_banner(webhook_status="", show_full_pirate=False):
    banner_lines = [line for line in BANNER_LINES.strip().splitlines() if line.strip()]
    pirate_lines = PIRATE_FULL_LINES if show_full_pirate else PIRATE_CENSORED_LINES

    if webhook_status:
        status_line = f"{Fore.GREEN}Webhook: OK ✅{Style.RESET_ALL}"
        banner_lines[-2] = banner_lines[-2] + f"    {status_line}"

    output = []
    for i in range(len(banner_lines)):
        art_line = f"{Fore.CYAN}{banner_lines[i]}{Style.RESET_ALL}"
        if i < len(pirate_lines):
            pirate_line = f"{Fore.YELLOW}{pirate_lines[i]}{Style.RESET_ALL}"
            output.append(f"{art_line}     {pirate_line}")
        else:
            output.append(art_line)
    return "\n".join(output)

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def calculate_checksum(file_path):
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

def get_file_size(file_path):
    return os.path.getsize(file_path)

def select_directory(title="Selecione a pasta"):
    root = tkinter.Tk()
    root.withdraw()
    folder = askdirectory(title=title)
    root.destroy()
    return folder

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if not content:
                    return {}
                return json.loads(content)
        except json.JSONDecodeError as e:
            logging.error(f"Erro ao decodificar JSON: {e}")
            print(f"Erro ao decodificar JSON: {e}")
            return {}
    return {}

def save_config(config):
    if not isinstance(config, dict):
        logging.error(f"Erro: config não é um dicionário, recebido: {config}")
        print(f"Erro: config não é um dicionário, recebido: {config}")
        return
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4)

def calculate_directory_checksum(directory):
    """Calcula o checksum SHA-256 de todos os arquivos em um diretório."""
    sha256 = hashlib.sha256()
    for root, _, files in os.walk(directory):
        for file in sorted(files):
            file_path = os.path.join(root, file)
            try:
                with open(file_path, "rb") as f:
                    while True:
                        data = f.read(65536)
                        if not data:
                            break
                        sha256.update(data)
            except Exception as e:
                logging.error(f"Erro ao calcular checksum do arquivo {file_path}: {e}")
    return sha256.hexdigest()

def create_backup(game_name, save_dir):
    temp_dir = os.path.join(os.getenv("TEMP"), "GameSaves")
    os.makedirs(temp_dir, exist_ok=True)

    files_to_backup = []
    for root, _, files in os.walk(save_dir): # Use os.walk to traverse subdirectories
        for file in files:
            file_path = os.path.join(root, file)
            if os.path.isfile(file_path): # Double check it's a file (important with os.walk)
                files_to_backup.append((file_path, os.path.getmtime(file_path)))

    files_to_backup.sort(key=lambda x: x[1], reverse=True)

    current_checksum = calculate_directory_checksum(save_dir)

    # Verificar  o checksum
    config = load_config()
    saved_checksum = config.get("games", {}).get(game_name, {}).get("checksum")

    if saved_checksum == current_checksum:
        print(f"{Fore.YELLOW}[!]{Style.RESET_ALL} Nenhum backup necessário para {game_name} - arquivos não modificados")
        logging.info(f"Nenhum backup necessário para {game_name} - arquivos não modificados")
        return None

    zip_path = os.path.join(temp_dir, f"{game_name}_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip")
    total_size = 0

    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for file_path, _ in files_to_backup: # Iterate over files found in subdirectories
            file_size = get_file_size(file_path)
            if total_size + file_size > MAX_ZIP_SIZE:
                break
            # Ensure we are writing the file inside the zip with a path relative to save_dir
            arcname = os.path.relpath(file_path, save_dir)
            zipf.write(file_path, arcname=arcname)
            total_size += file_size

    # checksum no config
    if "games" not in config:
        config["games"] = {}
    if game_name not in config["games"]:
        config["games"][game_name] = {}
    config["games"][game_name]["checksum"] = current_checksum
    save_config(config)

    logging.info(f"Backup criado: {zip_path}")
    return zip_path

def send_to_discord(zip_path, webhook_url):
    try:
        with open(zip_path, 'rb') as f:
            files = {'file': (os.path.basename(zip_path), f, 'application/zip')}
            response = requests.post(webhook_url, files=files)
        if response.status_code in (200, 204):
            logging.info(f"Backup enviado com sucesso para Discord: {zip_path}")
            return True
        else:
            logging.error(f"Falha ao enviar backup para Discord. Status: {response.status_code}, Resposta: {response.text}")
            print(f"{Fore.RED}[-]{Style.RESET_ALL} Falha ao enviar backup. Status: {response.status_code}")
            return False
    except Exception as e:
        logging.error(f"Erro ao enviar backup para Discord: {e}")
        print(f"{Fore.RED}[-]{Style.RESET_ALL} Erro ao enviar backup: {e}")
        return False

def main_menu():
    config = load_config()
    webhook_status = "OK" if config.get("discord_webhook") else ""
    clear_screen()
    print(generate_banner(webhook_status, show_full_pirate=False))
    print(f"{Fore.GREEN}[1]{Style.RESET_ALL} Configurar webhook")
    print(f"{Fore.GREEN}[2]{Style.RESET_ALL} Gerenciar jogos")
    print(f"{Fore.GREEN}[3]{Style.RESET_ALL} Iniciar monitoramento")
    print(f"{Fore.GREEN}[4]{Style.RESET_ALL} Sair")
    return input(f"\n{Fore.CYAN}Selecione uma opção: {Style.RESET_ALL}")

def webhook_menu():
    config = load_config()
    webhook_status = "OK" if config.get("discord_webhook") else ""
    clear_screen()
    print(generate_banner(webhook_status, show_full_pirate=False))
    print(f"{Fore.YELLOW}Configuração do Webhook{Style.RESET_ALL}")
    webhook_url = input("Digite a URL do webhook do Discord: ")
    config["discord_webhook"] = webhook_url
    save_config(config)
    logging.info(f"Webhook configurado: {webhook_url}")
    clear_screen()
    print(generate_banner("OK", show_full_pirate=False))
    print(f"{Fore.GREEN}Webhook configurado com sucesso! Status: OK ✅{Style.RESET_ALL}")
    input("\nPressione Enter para continuar...")

def game_management_menu():
    config = load_config()
    webhook_status = "OK" if config.get("discord_webhook") else ""
    clear_screen()
    print(generate_banner(webhook_status, show_full_pirate=False))
    print(f"{Fore.YELLOW}Gerenciamento de Jogos{Style.RESET_ALL}")
    print("\nJogos configurados:")
    games = config.get("games", {})

    for i, (name, details) in enumerate(games.items(), 1):
        print(f"{i}. {name} - Pasta: {details['save_dir']}")

    print("\nOpções:")
    print(f"{Fore.GREEN}[a]{Style.RESET_ALL} Adicionar jogo")
    print(f"{Fore.RED}[r]{Style.RESET_ALL} Remover jogo")
    print(f"{Fore.YELLOW}[e]{Style.RESET_ALL} Editar jogo")
    print(f"{Fore.BLUE}[v]{Style.RESET_ALL} Voltar")

    choice = input("\nSelecione uma opção: ").lower()

    if choice == 'a':
        add_game()
    elif choice == 'r':
        remove_game(games)
    elif choice == 'e':
        edit_game(games)
    elif choice == 'v':
        return
    else:
        print("Opção inválida!")
        time.sleep(2)

def suggest_save_directories(game_name):
    """Suggests potential save directories based on common locations."""
    user_home = os.path.expanduser("~")
    paths = [
        os.path.join(user_home, "Documents", "My Games"),
        os.path.join(user_home, "Documents"),
        os.path.join(user_home, "Saved Games"),
        os.path.join(user_home, "AppData", "Local"),
        os.path.join(user_home, "AppData", "Roaming"),
        "C:\\Program Files (x86)\\Steam\\userdata", # Common Steam userdata path, adjust drive if needed
        "D:\\Program Files (x86)\\Steam\\userdata", # Common Steam userdata path on D drive
    ]
    suggested_dirs = []
    for path in paths:
        if os.path.exists(path):
            suggested_dirs.append(path)
    return suggested_dirs

def find_save_folder_by_name(game_name, search_path):
    """Searches for save folders by game name within a given path."""
    potential_folders = []
    for root, dirs, files in os.walk(search_path):
        for file in files:
            if game_name.lower() in file.lower() and file.lower().endswith(SAVE_FILE_EXTENSIONS):
                potential_folders.append(root)
                break # Stop searching in this directory once a save file is found, to avoid duplicates from subfolders
        for dirname in dirs:
            if game_name.lower() in dirname.lower(): # Check directory names too
                potential_folders.append(os.path.join(root, dirname))

    return list(set(potential_folders)) # Remove duplicates

def add_game():
    config = load_config()
    webhook_status = "OK" if config.get("discord_webhook") else ""
    clear_screen()
    print(generate_banner(webhook_status, show_full_pirate=False))
    print(f"{Fore.GREEN}Adicionar Novo Jogo{Style.RESET_ALL}")
    game_name = input("Digite o nome do jogo: ")

    print("\nOpções de detecção da pasta de saves:")
    print(f"{Fore.GREEN}[1]{Style.RESET_ALL} Selecionar pasta manualmente")
    print(f"{Fore.GREEN}[2]{Style.RESET_ALL} Buscar automaticamente")

    detection_choice = input("Selecione a opção de detecção: ")

    if detection_choice == '2':
        print(f"\n{Fore.YELLOW}Buscando automaticamente pastas de save para '{game_name}'...{Style.RESET_ALL}")
        suggested_directories_list = suggest_save_directories(game_name)
        found_folders = []

        for search_dir in suggested_directories_list:
             found_folders.extend(find_save_folder_by_name(game_name, search_dir))

        if found_folders:
            print(f"\n{Fore.CYAN}Pastas de save potenciais encontradas:{Style.RESET_ALL}")
            for i, folder in enumerate(found_folders):
                print(f"{Fore.GREEN}[{i+1}]{Style.RESET_ALL} {folder}")

            print(f"{Fore.YELLOW}[0]{Style.RESET_ALL} Selecionar pasta manualmente") # Option to manually select even if auto-detect found folders

            folder_choice = input("\nSelecione o número da pasta ou '0' para manual: ")
            if folder_choice == '0':
                save_dir = select_directory(title=f"Selecione a pasta de saves para {game_name}")
            else:
                try:
                    chosen_index = int(folder_choice) - 1
                    if 0 <= chosen_index < len(found_folders):
                        save_dir = found_folders[chosen_index]
                    else:
                        print(f"{Fore.RED}Opção inválida. Selecionando pasta manualmente.{Style.RESET_ALL}")
                        save_dir = select_directory(title=f"Selecione a pasta de saves para {game_name}")
                except ValueError:
                    print(f"{Fore.RED}Entrada inválida. Selecionando pasta manualmente.{Style.RESET_ALL}")
                    save_dir = select_directory(title=f"Selecione a pasta de saves para {game_name}")

        else:
            print(f"{Fore.YELLOW}Nenhuma pasta de save automática encontrada. Selecione manualmente.{Style.RESET_ALL}")
            save_dir = select_directory(title=f"Selecione a pasta de saves para {game_name}")

    elif detection_choice == '1':
        save_dir = select_directory(title=f"Selecione a pasta de saves para {game_name}")
    else:
        print(f"{Fore.RED}Opção inválida. Selecionando pasta manualmente.{Style.RESET_ALL}")
        save_dir = select_directory(title=f"Selecione a pasta de saves para {game_name}")


    if "games" not in config:
        config["games"] = {}

    if save_dir: # Only add if a directory was actually selected
        config["games"][game_name] = {"save_dir": save_dir}
        save_config(config)
        logging.info(f"Jogo adicionado: {game_name} - {save_dir}")
        print(f"{Fore.GREEN}Jogo adicionado com sucesso! Pasta: {save_dir}{Style.RESET_ALL}")
    else:
        print(f"{Fore.RED}Nenhuma pasta de save selecionada. Jogo não adicionado.{Style.RESET_ALL}")

    input("\nPressione Enter para continuar...")


def remove_game(games):
    if not games:
        print("Nenhum jogo configurado!")
        return

    print("Selecione um jogo para remover:")
    for i, name in enumerate(games.keys(), 1):
        print(f"{i}. {name}")

    try:
        choice = int(input("Digite o número do jogo: ")) - 1
        game_name = list(games.keys())[choice]

        config = load_config()
        del config["games"][game_name]
        save_config(config)
        logging.info(f"Jogo removido: {game_name}")
        print(f"{Fore.GREEN}Jogo removido com sucesso!{Style.RESET_ALL}")
    except:
        print("Opção inválida!")

    input("\nPressione Enter para continuar...")

def edit_game(games):
    if not games:
        print("Nenhum jogo configurado!")
        return

    print("Selecione um jogo para editar:")
    for i, name in enumerate(games.keys(), 1):
        print(f"{i}. {name}")

    try:
        choice = int(input("Digite o número do jogo: ")) - 1
        game_name = list(games.keys())[choice]

        config = load_config()
        webhook_status = "OK" if config.get("discord_webhook") else ""
        clear_screen()
        print(generate_banner(webhook_status, show_full_pirate=False))
        print(f"{Fore.YELLOW}Editando: {game_name}{Style.RESET_ALL}")
        new_name = input(f"Novo nome [{game_name}]: ") or game_name
        new_dir = select_directory()

        config["games"][new_name] = {"save_dir": new_dir}
        if new_name != game_name:
            del config["games"][game_name]
        save_config(config)
        logging.info(f"Jogo editado: {game_name} -> {new_name}, nova pasta: {new_dir}")
        print(f"{Fore.GREEN}Jogo atualizado com sucesso!{Style.RESET_ALL}")
    except:
        print("Opção inválida!")

    input("\nPressione Enter para continuar...")

def monitoring_mode():
    config = load_config()
    webhook_status = "OK" if config.get("discord_webhook") else ""
    clear_screen()
    print(generate_banner(webhook_status, show_full_pirate=True))
    print(f"{Fore.CYAN}Modo de Monitoramento Ativo{Style.RESET_ALL}")
    print(f"{Fore.YELLOW}Pressione 'q' para sair do monitoramento.{Style.RESET_ALL}")

    webhook_url = config.get("discord_webhook")
    games = config.get("games", {})

    if not webhook_url:
        logging.error("Webhook não configurado ao iniciar monitoramento")
        print(f"{Fore.RED}Erro: Webhook não configurado!{Style.RESET_ALL}")
        input("\nPressione Enter para voltar...")
        return

    logging.info("Monitoramento iniciado")
    try:
        while True:
            for game_name, details in games.items():
                save_dir = details["save_dir"]
                if not os.path.exists(save_dir):
                    logging.warning(f"Pasta de save não encontrada: {save_dir}")
                    continue

                print(f"\n{Fore.BLUE}[*]{Style.RESET_ALL} Verificando saves para {game_name}...")
                zip_path = create_backup(game_name, save_dir)

                if zip_path and send_to_discord(zip_path, webhook_url):
                    print(f"{Fore.GREEN}[+]{Style.RESET_ALL} Backup enviado com sucesso para {game_name}")
                elif zip_path:
                    print(f"{Fore.RED}[-]{Style.RESET_ALL} Falha ao enviar backup para {game_name}")

                if zip_path:
                    shutil.rmtree(os.path.dirname(zip_path), ignore_errors=True)

            print(f"\n{Fore.YELLOW}[!]{Style.RESET_ALL} Aguardando mudanças... (Pressione 'q' para sair)")
            for _ in range(300):
                if keyboard.is_pressed('q'):
                    logging.info("Monitoramento interrompido pelo usuário (tecla 'q')")
                    print(f"\n{Fore.RED}[X]{Style.RESET_ALL} Monitoramento interrompido.")
                    return
                time.sleep(1)
    except Exception as e:
        logging.error(f"Erro inesperado no monitoramento: {e}")
        print(f"\n{Fore.RED}[X]{Style.RESET_ALL} Erro no monitoramento: {e}")
        input("\nPressione Enter para voltar...")

def main():
    while True:
        choice = main_menu()

        if choice == '1':
            webhook_menu()
        elif choice == '2':
            game_management_menu()
        elif choice == '3':
            monitoring_mode()
        elif choice == '4':
            logging.info("Programa encerrado pelo usuário")
            print(f"{Fore.CYAN}Encerrando...{Style.RESET_ALL}")
            break
        else:
            print("Opção inválida!")
            time.sleep(2)

if __name__ == "__main__":
    main()