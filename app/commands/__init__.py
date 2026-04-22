def register_commands(app):
    from app.commands.backfill_locations import backfill_location_coordinates_command
    from app.commands.seed_home import seed_home_command

    app.cli.add_command(seed_home_command)
    app.cli.add_command(backfill_location_coordinates_command)
