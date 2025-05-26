import overpass
import logging
from typing import Union

# Configure logging
logger = logging.getLogger(__name__)

# Initialize the Overpass API client
# It's good practice to initialize it once if the module is imported multiple times,
# but for simplicity in a function, it can be inside or outside.
# For a module, initializing outside the function is better if it's stateless
# or if the state (like endpoint, timeout) is meant to be module-global.
API_CLIENT = overpass.API(timeout=30) # Set a reasonable timeout

def get_speed_limit_for_location(latitude: float, longitude: float, radius_meters: int = 50) -> Union[str, None]:
    """
    Queries OpenStreetMap for the speed limit of a road near the given GPS coordinates.

    Args:
        latitude: The latitude of the location.
        longitude: The longitude of the location.
        radius_meters: The radius (in meters) to search around the location.

    Returns:
        The speed limit as a string (e.g., "50", "30 mph") if found, otherwise None.
    """
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        logger.error(f"Invalid coordinates provided: lat={latitude}, lon={longitude}")
        return None

    # Construct the Overpass QL query
    # This query looks for 'ways' (roads) that have a 'highway' tag
    # and a 'maxspeed' tag, within the specified radius of the coordinates.
    # It prioritizes ways that are likely to be actual roads.
    query = (
        f"way(around:{radius_meters},{latitude},{longitude})"
        f"[highway][highway!~'^(footway|cycleway|path|steps|corridor|elevator|escalator|bridleway|construction|proposed)$']"
        f"[maxspeed];"
        f"(._;>;);"
        f"out tags;"
    )
    # A simpler query that the 'overpass' library can often handle directly for GeoJSON:
    simple_query = f"way(around:{radius_meters},{latitude},{longitude})['highway']['maxspeed'][highway!~'^(footway|cycleway|path|steps)$']"

    logger.debug(f"Querying OSM for speed limit at lat={latitude}, lon={longitude}, radius={radius_meters}m")
    logger.debug(f"Overpass query (simplified for library): {simple_query}")

    try:
        response = API_CLIENT.get(simple_query, verbosity='tags')

        if response and response.get('features'):
            logger.info(f"Found {len(response['features'])} road(s) with speed limits nearby.")
            # Prioritize the closest way if multiple are found, though Overpass doesn't directly give distance for 'around'.
            # For simplicity, we'll take the first one that has a maxspeed.
            for feature in response['features']:
                properties = feature.get('properties', {})
                speed_limit = properties.get('maxspeed')
                
                if speed_limit:
                    road_name = properties.get('name', 'N/A')
                    highway_type = properties.get('highway', 'N/A')
                    logger.info(f"  - Road: {road_name} (Type: {highway_type}), Speed Limit: {speed_limit}")
                    return str(speed_limit) # Return the first valid speed limit found
            logger.warning("No features with a 'maxspeed' property found in the response features.")
        else:
            logger.info("No roads with speed limits found nearby or empty features in response.")
            if response:
                logger.debug(f"Raw response features: {response.get('features')}")

    except overpass.errors.OverpassTooManyRequests as e:
        logger.error(f"Overpass API rate limit exceeded: {e}")
    except overpass.errors.OverpassGatewayTimeout as e:
        logger.error(f"Overpass API gateway timeout: {e}")
    except overpass.errors.OverpassBadRequest as e:
        logger.error(f"Overpass API bad request. Query: {API_CLIENT.last_query_body if hasattr(API_CLIENT, 'last_query_body') else simple_query}. Error: {e}")
    except overpass.errors.OverpassUnknownError as e:
        logger.error(f"An unknown Overpass API error occurred: {e}")
    except Exception as e:
        logger.error(f"An unexpected error occurred during OSM query: {e}", exc_info=True)
    
    return None

if __name__ == '__main__':
    # Example Usage:
    logging.basicConfig(level=logging.INFO)
    # Test coordinates (e.g., somewhere in a city)
    # Eiffel Tower, Paris (approx)
    test_lat, test_lon = 48.8584, 2.2945 
    logger.info(f"Testing with coordinates: Latitude={test_lat}, Longitude={test_lon}")
    limit = get_speed_limit_for_location(test_lat, test_lon)
    if limit:
        logger.info(f"Determined speed limit: {limit}")
    else:
        logger.info("Could not determine speed limit from OSM.")

    # Test with known no-speed-limit area or invalid coords
    logger.info("\nTesting with potentially no speed limit area (e.g., middle of ocean or invalid)")
    # Pacific Ocean (approx)
    test_lat_ocean, test_lon_ocean = 0, -150
    limit_ocean = get_speed_limit_for_location(test_lat_ocean, test_lon_ocean)
    if limit_ocean:
        logger.info(f"Determined speed limit (ocean): {limit_ocean}")
    else:
        logger.info("Could not determine speed limit from OSM (ocean test).")

    # Invalid coordinates
    logger.info("\nTesting with invalid coordinates")
    limit_invalid = get_speed_limit_for_location(100, 200)
    if limit_invalid:
        logger.info(f"Determined speed limit (invalid): {limit_invalid}")
    else:
        logger.info("Could not determine speed limit from OSM (invalid coords test).")
