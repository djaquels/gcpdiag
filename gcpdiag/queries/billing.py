# Copyright 2021 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Lint as: python3
"""Queries related to GCP Billing Accounts."""

import logging
from typing import List, Optional

import googleapiclient.errors

from gcpdiag import caching, config, models
from gcpdiag.queries import apis, apis_utils
from gcpdiag.utils import GcpApiError

API_VERSION = 'v1'


class BillingAccount(models.Resource):
  """Represents a Cloud Billing Account.

  See also the API documentation:
  https://cloud.google.com/billing/docs/reference/rest/v1/billingAccounts
  """

  @property
  def full_path(self) -> str:
    return self._resource_data['name']

  @property
  def name(self) -> str:
    return self._resource_data['name']

  @property
  def display_name(self) -> str:
    return self._resource_data['displayName']

  def is_open(self) -> bool:
    return self._resource_data['open']

  def is_master(self) -> bool:
    return len(self._resource_data['masterBillingAccount']) > 0

  def list_projects(self) -> list:
    return get_all_projects_in_billing_account(self.name)

  def __init__(self, project_id, resource_data):
    super().__init__(project_id=project_id)
    self._resource_data = resource_data


class ProjectBillingInfo(models.Resource):
  """Represents a Billing Information about a Project.

  See also the API documentation:
  https://cloud.google.com/billing/docs/reference/rest/v1/ProjectBillingInfo
  """

  @property
  def full_path(self) -> str:
    return self._resource_data['name']

  @property
  def name(self) -> str:
    return self._resource_data['name']

  @property
  def billing_account_name(self) -> str:
    return self._resource_data['billingAccountName']

  def is_billing_enabled(self) -> bool:
    return self._resource_data['billingEnabled']

  def __init__(self, project_id, resource_data):
    super().__init__(project_id=project_id)
    self._resource_data = resource_data


class CostInsights(models.Resource):
  """Represents a Costs Insights object"""

  @property
  def full_path(self) -> str:
    return self._resource_data['name']

  @property
  def description(self) -> str:
    return self._resource_data['description']

  @property
  def anomaly_details(self) -> dict:
    return self._resource_data['content']['anomalyDetails']

  @property
  def forecasted_units(self) -> str:
    return self.anomaly_details['forecastedCostData']['cost']['units']

  @property
  def forecasted_currency(self) -> str:
    return self.anomaly_details['forecastedCostData']['cost']['currencyCode']

  @property
  def actual_units(self) -> str:
    return self.anomaly_details['actualCostData']['cost']['units']

  @property
  def actual_currency(self) -> str:
    return self.anomaly_details['actualCostData']['cost']['currencyCode']

  @property
  def start_time(self) -> str:
    return self.anomaly_details['costSlice']['startTime']

  @property
  def end_time(self) -> str:
    return self.anomaly_details['costSlice']['endTime']

  @property
  def anomaly_type(self) -> str:
    return 'Below' if self._resource_data['insightSubtype'] == \
                         'COST_BELOW_FORECASTED' else 'Above'

  def is_anomaly(self) -> bool:
    if 'description' in self._resource_data.keys():
      return 'This is a cost anomaly' in self.description
    return False

  def build_anomaly_description(self):
    return self.description + '\nCost ' + self.anomaly_type + \
           ' forcast, Forecasted: ' + self.forecasted_units + \
           ' ' + self.forecasted_currency + ', Actual: ' + \
           self.actual_units + ' ' + self.actual_currency + \
           '\nAnomaly Period From: ' + self.start_time + ', To: ' + self.end_time

  def __init__(self, project_id, resource_data):
    super().__init__(project_id=project_id)
    self._resource_data = resource_data


@caching.cached_api_call
def get_billing_info(project_id):
  """Get Billing Information for a project, caching the result."""
  project_api = apis.get_api('cloudbilling', 'v1', project_id)
  query = project_api.projects().getBillingInfo(project_id)
  logging.info('fetching Billing Information for project %s', project_id)
  try:
    resource_data = query.execute(num_retries=config.API_RETRIES)
  except googleapiclient.errors.HttpError as err:
    raise GcpApiError(err) from err
  return resource_data


@caching.cached_api_call
def get_billing_account(project_id: str) -> Optional[BillingAccount]:
  """Get a Billing Account object by its project name, caching the result."""

  billing_info = ProjectBillingInfo(project_id, get_billing_info(project_id))
  if not billing_info.is_billing_enabled():
    return None

  billing_account_api = apis.get_api('cloudbilling', 'v1', project_id)
  query = billing_account_api.billingAccounts().get(
      name=billing_info.billing_account_name)
  logging.info('fetching Billing Account for project %s', project_id)
  try:
    resource_data = query.execute(num_retries=config.API_RETRIES)
  except googleapiclient.errors.HttpError as err:
    raise GcpApiError(err) from err
  return BillingAccount(project_id, resource_data)


@caching.cached_api_call
def get_all_billing_accounts(project_id: str) -> List[BillingAccount]:
  """Get all Billing Accounts that current user has permission to view"""
  # return _get_all_pages_of_a_resource('billingAccounts', 'v1', project_id,
  #                                     'billingAccounts', BillingAccount)
  accounts = []
  api = apis.get_api('cloudbilling', API_VERSION, project_id)

  for account in apis_utils.list_all(
      request=api.billingAccounts().list(),
      next_function=api.billingAccounts().list_next,
      response_keyword='billingAccounts'):
    accounts.append(BillingAccount(project_id, account))
  return accounts


@caching.cached_api_call
def get_all_projects_in_billing_account(
    billing_account_name: str) -> List[ProjectBillingInfo]:
  """Get all projects associated with the Billing Account that current user has
  permission to view"""
  projects = []
  api = apis.get_api('cloudbilling', API_VERSION, billing_account_name)

  for project in apis_utils.list_all(
      request=api.billingAccounts().projects().list(),
      next_function=api.billingAccounts().projects().list_next,
      response_keyword='projectBillingInfo'):
    projects.append(ProjectBillingInfo(project['projectId'], project))
  return projects


@caching.cached_api_call
def get_cost_insights_for_a_project(project_id: str):
  """Get cost insights for the project"""
  billing_account = get_billing_account(project_id)

  # If Billing Account is closed or is a reseller account then Cost Insights
  # are not available
  if (not billing_account.is_open()) or billing_account.is_master():
    return None

  cost_insights_api = apis.get_api('recommender', 'v1', project_id)
  query = cost_insights_api.billingAccounts().locations().insightTypes(). \
    insights().get('google.billing.CostInsight')
  logging.info('fetching Cost Insights for project %s', project_id)
  try:
    resource_data = query.execute(num_retries=config.API_RETRIES)
  except googleapiclient.errors.HttpError as err:
    raise GcpApiError(err) from err
  return CostInsights(project_id, resource_data)
