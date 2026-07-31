from eagle.cv_clusters import CV_CLUSTERS


def test_all_operational_clusters_exist() -> None:
    expected = {
        "CV_FRONT_OFFICE",
        "CV_OPERATIONS_ADMIN",
        "CV_HOUSEKEEPING",
        "CV_HOSPITALITY_ALLROUNDER",
        "CV_FOOD_PROCESSING",
        "CV_GENERAL_LABOUR",
    }
    assert expected.issubset(CV_CLUSTERS)


def test_clusters_do_not_claim_unverified_credentials() -> None:
    text = " ".join(
        str(value)
        for cluster in CV_CLUSTERS.values()
        for value in cluster.values()
    ).lower()
    for forbidden in (
        "driver licence held",
        "opera pms expert",
        "australian hotel experience",
        "rsa certified",
        "qualified chef",
    ):
        assert forbidden not in text
