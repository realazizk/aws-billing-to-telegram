from collections import defaultdict
import boto3
import datetime
import os
import requests
import sys
import requests

n_days = 7
today = datetime.datetime.today()
week_ago = today - datetime.timedelta(days=n_days)

sparks = ['▁', '▂', '▃', '▄', '▅', '▆', '▇']


def sparkline(datapoints):
    lowest = min(datapoints)
    highest = max(datapoints)
    if highest == 0:
        highest = 1

    line = ""
    for i in range(n_days):
        if i < len(datapoints):
            dp = datapoints[i]
            which_spark = int((dp / highest) * (len(sparks) - 1))
            line += (sparks[which_spark])
        else:
            line += (sparks[0])

    return line


def report_cost(event, context):
    aws_access_key = os.environ.get('ACCESS_KEY')
    aws_secret_key = os.environ.get('SECRET_KEY')
    client = boto3.client('ce', aws_access_key_id=aws_access_key,
                          aws_secret_access_key=aws_secret_key)

    query = {
        "TimePeriod": {
            "Start": week_ago.strftime('%Y-%m-%d'),
            "End": today.strftime('%Y-%m-%d'),
        },
        "Granularity": "DAILY",
        "Filter": {
            "Not": {
                "Dimensions": {
                    "Key": "RECORD_TYPE",
                    "Values": [
                        "Credit",
                        "Refund",
                        "Upfront",
                        "Support",
                    ]
                }
            }
        },
        "Metrics": ["UnblendedCost"],
        "GroupBy": [
            {
                "Type": "DIMENSION",
                "Key": "SERVICE",
            },
        ],
    }

    result = client.get_cost_and_usage(**query)

    buffer = "%-40s\t %-7s\t $%5s\n" % ("Service", "Last 7d", "Yday")

    cost_by_days = []
    services = []
    # Build a map of service -> array of daily costs for the time frame
    for day in result['ResultsByTime']:
        cost_by_services = defaultdict(list)
        for group in day['Groups']:
            key = group['Keys'][0]
            cost = float(group['Metrics']['UnblendedCost']['Amount'])
            cost_by_services[key] = cost
            services.append(key)
        cost_by_days.append(cost_by_services)
    services = set(services)

    cost_per_day_by_service = defaultdict(list)
    for cost_by_day in cost_by_days:
        for service in services:
            if (cost_by_day[service] == []):
                cost_per_day_by_service[service].append(0.0)
            else:
                cost_per_day_by_service[service].append(cost_by_day[service])

    # Sort the map by yesterday's cost
    most_expensive_yesterday = sorted(
        cost_per_day_by_service.items(), key=lambda i: i[1][-1], reverse=True)

    for service_name, costs in most_expensive_yesterday:
        buffer += "%-40s\t %s\t $%5.2f\n" % (service_name,
                                             sparkline(costs), costs[-1])

    total_costs = [0.0] * n_days
    for day_number in range(n_days):
        for service_name, costs in most_expensive_yesterday:
            try:
                total_costs[day_number] += costs[day_number]
            except IndexError:
                total_costs[day_number] += 0.0

    buffer += "%-40s\t %s\t $%5.2f\n" % ("Total",
                                         sparkline(total_costs), total_costs[-1])

    credits_expire_date = os.environ.get('CREDITS_EXPIRE_DATE')
    if credits_expire_date:
        credits_expire_date = datetime.datetime.strptime(
            credits_expire_date, "%m/%d/%Y")

        credits_remaining_as_of = os.environ.get('CREDITS_REMAINING_AS_OF')
        credits_remaining_as_of = datetime.datetime.strptime(
            credits_remaining_as_of, "%m/%d/%Y")

        credits_remaining = float(os.environ.get('CREDITS_REMAINING'))

        days_left_on_credits = (credits_expire_date -
                                credits_remaining_as_of).days
        allowed_credits_per_day = credits_remaining / days_left_on_credits

        relative_to_budget = (
            total_costs[-1] / allowed_credits_per_day) * 100.0

        if relative_to_budget < 60:
            emoji = ":white_check_mark:"
        elif relative_to_budget > 110:
            emoji = ":rotating_light:"
        else:
            emoji = ":warning:"

        summary = "%s Yesterday's cost of $%5.2f is %.0f%% of credit budget $%5.2f for the day." % (
            emoji,
            total_costs[-1],
            relative_to_budget,
            allowed_credits_per_day,
        )
    else:
        summary = "Yesterday's cost was $%5.2f." % (total_costs[-1])

    chat_id = os.environ.get('TELEGRAM_USER')
    telegram_token = os.environ.get('TELEGRAM_BOT_TOKEN')

    api_url = f"https://api.telegram.org/bot{telegram_token}/"

    params = {'chat_id': chat_id, 'parse_mode': 'Markdown', 'text': summary +
              "\n\n```\n" + buffer + "\n```"}
    res = requests.post(api_url + "sendMessage", data=params).json()

    if res["ok"]:
        return {
            'statusCode': 200,
            'body': res['result'],
        }
    else:
        return {
            'statusCode': 400,
            'body': res
        }
