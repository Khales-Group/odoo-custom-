odoo.define("kh_approvals.boq_website", function (require) {
  "use strict";

  var ajax = require("web.ajax");
  var core = require("web.core");

  $(document).ready(function () {
    // 1. Live Calculation Logic
    $(".js_unit_price").on("input", function () {
      var input = $(this);
      var qty = parseFloat(input.data("qty"));
      var price = parseFloat(input.val()) || 0;
      var total = qty * price;

      // Update Line Total
      input.closest("tr").find(".js_line_total").text(total.toFixed(2));

      // Update Grand Total
      calculateGrandTotal();
    });

    function calculateGrandTotal() {
      var grandTotal = 0;
      $(".js_unit_price").each(function () {
        var qty = parseFloat($(this).data("qty"));
        var price = parseFloat($(this).val()) || 0;
        grandTotal += qty * price;
      });
      $("#js_grand_total").text(grandTotal.toFixed(2));
    }

    // 2. Submit Logic
    $("#btn_submit_boq").on("click", function (e) {
      e.preventDefault();

      var applicantName = $("#applicant_name").val();
      if (!applicantName) {
        alert("Please enter your Company/Contractor Name.");
        return;
      }

      var lines = [];
      $(".js_unit_price").each(function () {
        var price = parseFloat($(this).val()) || 0;
        if (price > 0) {
          lines.push({
            product_id: $(this).data("id"),
            qty: $(this).data("qty"),
            price: price,
          });
        }
      });

      // Send to Python Controller
      ajax
        .jsonRpc("/boq/submit", "call", {
          project_id: 1, // You need to inject this ID dynamically in the template
          applicant_name: applicantName,
          lines: lines,
        })
        .then(function (result) {
          if (result.success) {
            // Replace body with Success Message
            $(".o_kh_boq_wrapper").html(
              '<div class="container text-center mt-5 pt-5">' +
                '<i class="fa fa-check-circle text-success fa-5x mb-3"></i>' +
                "<h1>Submission Received!</h1>" +
                "<p>Reference ID: #" +
                result.submission_id +
                "</p>" +
                "</div>",
            );
          }
        });
    });
  });
});
