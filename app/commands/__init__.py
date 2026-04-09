def register_commands(app):
    from app.commands.seed_home import seed_home_command

    app.cli.add_command(seed_home_command)
