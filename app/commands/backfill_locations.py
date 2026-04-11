import click

from app.extensions import db
from app.models.customer import Customer
from app.models.restaurant import Restaurant
from app.services.location_service import resolve_address_for_area


def _backfill_record(record, address, area, allow_seed_fallback=False):
    if not address:
        return False

    location = resolve_address_for_area(address, area, allow_seed_fallback=allow_seed_fallback)
    if not location:
        return False

    record.latitude = location["lat"]
    record.longitude = location["lon"]
    if area:
        record.area = area
    return True


@click.command("backfill-location-coordinates")
def backfill_location_coordinates_command():
    """Backfill latitude and longitude for existing customers and restaurants."""
    updated_customers = 0
    updated_restaurants = 0

    for customer in Customer.query.all():
        if customer.latitude is not None and customer.longitude is not None:
            continue
        if _backfill_record(customer, customer.address, customer.area, allow_seed_fallback=False):
            updated_customers += 1

    for restaurant in Restaurant.query.all():
        if restaurant.latitude is not None and restaurant.longitude is not None:
            continue
        if _backfill_record(restaurant, restaurant.address, restaurant.area, allow_seed_fallback=True):
            updated_restaurants += 1

    db.session.commit()
    click.echo(
        f"Backfill done: customers={updated_customers}, restaurants={updated_restaurants}"
    )
