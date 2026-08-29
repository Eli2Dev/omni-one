# OmniOne

O OmniOne é um controlador de bandeja do Windows para o servidor OmniRoute e o Claude Code.

## Instalar

1. Execute `install_tray_app.ps1` no PowerShell.
2. Use o atalho **OmniOne** criado na Área de Trabalho ou encontre-o na bandeja do sistema.

O instalador cria também a inicialização automática do Windows. No menu do ícone é possível iniciar, parar ou reiniciar o servidor, abrir o Claude Code em um workspace, consultar os logs e abrir o painel.

## Workspaces em outro local

Por padrão, o OmniOne lista projetos em `C:\\Users\\seu-usuário\\Workspace`. Para usar outro lugar, defina a variável de ambiente `OMNIONE_WORKSPACE_ROOT` com a pasta que contém seus projetos e abra o OmniOne novamente.

## Recriar o executável

```powershell
python -m PyInstaller omnione_tray.spec --clean
```

O executável gerado fica em `dist\\OmniOne Tray.exe`.

---

Made by [ProdByE²](https://github.com/Eli2Dev/omni-one)
