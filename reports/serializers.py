from datetime import date, timedelta
from rest_framework import serializers

class TimeSeriesQuerySerializer(serializers.Serializer):
    BUCKETS = (("day", "day"), ("week", "week"), ("month", "month"))
    bucket = serializers.ChoiceField(choices=BUCKETS, default="day")
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)

    def validate(self, data):
        d_to = data.get("date_to") or date.today()
        d_from = data.get("date_from") or (d_to - timedelta(days=30))
        if d_from > d_to:
            d_from, d_to = d_to, d_from
        data["date_from"], data["date_to"] = d_from, d_to
        return data


class TemplatesUsageQuerySerializer(serializers.Serializer):
    top = serializers.IntegerField(required=False, min_value=1, max_value=100, default=10)
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)

    def validate(self, data):
        if data.get("date_from") or data.get("date_to"):
            from datetime import date
            d_to = data.get("date_to") or date.today()
            d_from = data.get("date_from") or d_to
            if d_from > d_to:
                d_from, d_to = d_to, d_from
            data["date_from"], data["date_to"] = d_from, d_to
        return data


class ExportPetitionsQuerySerializer(serializers.Serializer):
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)
    template = serializers.IntegerField(required=False, min_value=1)
    cliente = serializers.IntegerField(required=False, min_value=1)

    def validate(self, data):
        if data.get("date_from") or data.get("date_to"):
            from datetime import date
            d_to = data.get("date_to") or date.today()
            d_from = data.get("date_from") or d_to
            if d_from > d_to:
                d_from, d_to = d_to, d_from
            data["date_from"], data["date_to"] = d_from, d_to
        return data
